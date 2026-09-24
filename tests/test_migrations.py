"""La chaîne de migrations, rejouée pour de vrai.

Deux raisons d'exister :

* Activer les clés étrangères SQLite imposait de les couper pendant les
  migrations, qui recréent des tables. Une première version de ce réglage
  laissait une transaction ouverte : Alembic affichait « Running upgrade » à
  chaque étape, puis tout était annulé en silence — aucune version enregistrée,
  tables absentes. Sur le Raspberry, ``flask db upgrade`` aurait semblé réussir
  sans rien appliquer.
* Une migration qui reconstruit une table encore désignée par une autre —
  SQLite ne sait pas supprimer une colonne sans reconstruire — échouerait sur
  une base réelle, clés actives. Aucune migration existante ne le fait (SQLite
  ajoute une colonne sans reconstruire) : on en fabrique une, sur une copie
  isolée du dossier des migrations.

Chaque test lance ``flask db upgrade`` dans un processus séparé, sur un vrai
fichier, comme en production.
"""

import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import textwrap

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[1]
TETE = "f3b4c5d6e7a8"
# Crée reservation_segment ; la migration suivante recrée reservation.
AVANT_RECREATION = "3f78231a732c"

TABLES_ATTENDUES = {
    "alembic_version", "user", "vehicle", "reservation", "reservation_segment",
    "vehicle_unavailability", "login_attempt", "credential_handoff",
    "notification_settings", "vehicle_loan",
}


def _flask(base, *args, dossier=None):
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": f"sqlite:///{base}",
        "SECRET_KEY": "test-migrations",
        "MAIL_SERVER": "127.0.0.1",
        "MAIL_PORT": "9",
        "FLASK_APP": "app.py",
    })
    if dossier is not None:
        # « flask db upgrade -d dossier » : l'option suit la sous-commande.
        args = (*args[:2], "-d", str(dossier), *args[2:])
    return subprocess.run([sys.executable, "-m", "flask", *args], cwd=RACINE,
                          env=env, capture_output=True, text=True, timeout=120)


def _tables(base):
    with sqlite3.connect(base) as c:
        return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}


def _version(base):
    with sqlite3.connect(base) as c:
        return [r[0] for r in c.execute("select version_num from alembic_version")]


def test_full_chain_is_really_applied(tmp_path):
    """Pas seulement affichée : enregistrée, tables comprises."""
    base = tmp_path / "vide.db"
    resultat = _flask(base, "db", "upgrade")
    assert resultat.returncode == 0, resultat.stderr[-2000:]
    assert _version(base) == [TETE], "migrations annulées en silence"
    manquantes = TABLES_ATTENDUES - _tables(base)
    assert not manquantes, f"tables absentes : {manquantes}"


def _inserer_une_reservation_segmentee(base):
    with sqlite3.connect(base) as c:
        c.execute("insert into user (id, name, email, role, password_hash, status) "
                  "values (1, 'Dupont Jean', 'j@ex.fr', 'user', 'x', 'active')")
        c.execute("insert into vehicle (id, code, label) values (1, 'VL1', 'Kangoo')")
        c.execute("insert into reservation (id, vehicle_id, user_id, start_at, end_at, status) "
                  "values (1, 1, 1, '2026-10-05 08:00:00', '2026-10-06 17:00:00', 'approved')")
        c.execute("insert into reservation_segment (id, reservation_id, vehicle_id, start_at, end_at) "
                  "values (1, 1, 1, '2026-10-05 08:00:00', '2026-10-05 17:00:00')")


def _compter(base, table):
    with sqlite3.connect(base) as c:
        return c.execute(f"select count(*) from {table}").fetchone()[0]


def test_existing_data_survives_the_upgrade(tmp_path):
    """Le cas du Raspberry : une base ancienne, déjà remplie, mise à jour."""
    base = tmp_path / "avec-donnees.db"
    assert _flask(base, "db", "upgrade", AVANT_RECREATION).returncode == 0
    _inserer_une_reservation_segmentee(base)

    resultat = _flask(base, "db", "upgrade")
    assert resultat.returncode == 0, resultat.stderr[-2000:]
    assert _version(base) == [TETE]
    assert _compter(base, "reservation") == 1
    assert _compter(base, "reservation_segment") == 1
    with sqlite3.connect(base) as c:
        assert c.execute("pragma foreign_key_check").fetchall() == []


def test_a_future_table_rebuild_is_not_blocked(tmp_path):
    """Reconstruire ``reservation`` supprime l'ancienne table, que les segments
    désignent. Clés actives pendant la migration, SQLite refuserait."""
    dossier = tmp_path / "migrations"
    shutil.copytree(RACINE / "migrations", dossier,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (dossier / "versions" / "zz_reconstruction.py").write_text(textwrap.dedent(f'''
        """reconstruire reservation (essai)"""
        from alembic import op

        revision = "zz_reconstruction"
        down_revision = "{TETE}"
        branch_labels = None
        depends_on = None


        def upgrade():
            with op.batch_alter_table("reservation", recreate="always"):
                pass


        def downgrade():
            pass
    '''), encoding="utf-8")

    base = tmp_path / "reconstruction.db"
    # Monter jusqu'à la tête actuelle, remplir, puis reconstruire.
    assert _flask(base, "db", "upgrade", TETE, dossier=dossier).returncode == 0
    _inserer_une_reservation_segmentee(base)

    resultat = _flask(base, "db", "upgrade", dossier=dossier)
    assert resultat.returncode == 0, resultat.stderr[-2000:]
    assert _version(base) == ["zz_reconstruction"]
    assert _compter(base, "reservation") == 1
    assert _compter(base, "reservation_segment") == 1


def test_integrity_command_reports_a_clean_base(tmp_path):
    base = tmp_path / "saine.db"
    assert _flask(base, "db", "upgrade").returncode == 0
    resultat = _flask(base, "check-integrity")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert "aucune référence cassée" in resultat.stdout


def test_integrity_command_names_a_broken_reference(tmp_path):
    """Données d'avant les clés étrangères : la commande doit les montrer."""
    base = tmp_path / "abimee.db"
    assert _flask(base, "db", "upgrade").returncode == 0
    with sqlite3.connect(base) as c:
        c.execute("pragma foreign_keys=off")
        c.execute("insert into reservation_segment (reservation_id, vehicle_id, start_at, end_at) "
                  "values (999, 999, '2026-10-05 08:00:00', '2026-10-05 17:00:00')")
    resultat = _flask(base, "check-integrity")
    assert resultat.returncode == 1
    assert "reservation_segment" in resultat.stdout
