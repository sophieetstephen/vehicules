"""Ce que la sauvegarde nocturne envoie réellement hors du Raspberry.

Elle ne copiait que la base et le ``.env``. Les PDF d'archive annuelle — la
trace permanente qui justifie, à terme, de supprimer les réservations de
l'année — restaient sur le seul SSD : une panne de disque les emportait tous.

Le script est exécuté pour de vrai, avec un faux ``rclone`` qui note ce qu'on
lui demande de copier.
"""

import os
import shutil
import sqlite3
import subprocess

import pytest

SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools", "backup_db.sh"))

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash est nécessaire pour exécuter le script"
)

# ``sqlite3 <base> ".backup '<cible>'"`` : on teste ce que le script envoie et
# où, pas la commande de SQLite. Un doublon suffit, et le test tourne partout.
FAUX_SQLITE3 = r"""#!/usr/bin/env bash
cible=${2#.backup }
cible=${cible#\'}
cible=${cible%\'}
cp "$1" "$cible"
"""


@pytest.fixture
def atelier(tmp_path):
    """Une base, un .env, deux PDF d'archive et un rclone en trompe-l'œil."""
    base = tmp_path / "vehicules.db"
    sqlite3.connect(base).execute("create table t (x int)")

    (tmp_path / ".env").write_text("SECRET_KEY=x\n", encoding="utf-8")

    archives = tmp_path / "backups" / "archives" / "2025"
    archives.mkdir(parents=True)
    (archives / "planning_2025-01.pdf").write_bytes(b"%PDF-1.7 janvier")
    (archives / "planning_2025-02.pdf").write_bytes(b"%PDF-1.7 fevrier")

    journal = tmp_path / "rclone.log"
    faux = tmp_path / "bin"
    faux.mkdir()
    (faux / "rclone").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{journal}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (faux / "rclone").chmod(0o755)

    (faux / "sqlite3").write_text(FAUX_SQLITE3, encoding="utf-8")
    (faux / "sqlite3").chmod(0o755)
    return tmp_path, base, journal, faux


def _lancer(atelier, **surcharges):
    tmp_path, base, journal, faux = atelier
    env = dict(os.environ)
    env["PATH"] = f"{faux}{os.pathsep}{env['PATH']}"
    env.update({"DB_PATH": str(base), "COMPRESS": "false", "REMOTE_URI": "gdrive:sauvegardes"})
    env.update(surcharges)
    resultat = subprocess.run(["bash", SCRIPT], cwd=tmp_path, env=env,
                              capture_output=True, text=True)
    copies = journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []
    return resultat, copies


def test_archives_are_sent_off_the_raspberry(atelier):
    """Sans cela, la seule copie des archives vivait sur le SSD."""
    resultat, copies = _lancer(atelier)
    assert resultat.returncode == 0, resultat.stderr
    envois = [c for c in copies if "archives" in c]
    assert envois, "les archives ne sont pas copiées"
    assert envois[0].endswith("gdrive:sauvegardes/archives"), envois[0]


def test_database_and_env_are_still_sent(atelier):
    """La correction ne doit rien retirer de ce qui partait déjà."""
    _, copies = _lancer(atelier)
    assert any("vehicules_" in c for c in copies), "base absente"
    assert any("env_" in c for c in copies), ".env absent"


def test_nothing_leaves_without_a_destination(atelier):
    """Sans REMOTE_URI, la sauvegarde reste locale."""
    resultat, copies = _lancer(atelier, REMOTE_URI="")
    assert resultat.returncode == 0, resultat.stderr
    assert copies == []


def test_missing_archive_directory_is_not_an_error(atelier):
    """Une installation qui n'a encore rien archivé ne doit pas échouer."""
    tmp_path, _, _, _ = atelier
    shutil.rmtree(tmp_path / "backups" / "archives")
    resultat, copies = _lancer(atelier)
    assert resultat.returncode == 0, resultat.stderr
    assert not any("archives" in c for c in copies)


def test_archives_survive_the_thirty_day_cleanup(atelier):
    """Le ménage local vise les copies datées de la base, pas les archives."""
    import time

    tmp_path, _, _, _ = atelier
    ancien = tmp_path / "backups" / "archives" / "2025" / "planning_2025-01.pdf"
    il_y_a_soixante_jours = time.time() - 60 * 24 * 3600
    os.utime(ancien, (il_y_a_soixante_jours, il_y_a_soixante_jours))

    resultat, _ = _lancer(atelier)
    assert resultat.returncode == 0, resultat.stderr
    assert ancien.exists(), "une archive de plus de 30 jours a été supprimée"


def test_remote_failure_is_reported(atelier):
    """Un échec de copie doit faire échouer le service, pas passer inaperçu."""
    tmp_path, _, _, faux = atelier
    (faux / "rclone").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *archives* ]]; then echo boum >&2; exit 3; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (faux / "rclone").chmod(0o755)
    resultat, _ = _lancer(atelier)
    assert resultat.returncode != 0
    assert "archives" in resultat.stderr
