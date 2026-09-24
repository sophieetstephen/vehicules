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


# Faux rclone : note chaque copie ; à « listremotes --long », décrit un remote
# Drive en clair (gdrive) et un remote chiffré (gdrive-chiffre).
FAUX_RCLONE = """#!/usr/bin/env bash
if [ "$1" = "listremotes" ] || [ "$3" = "listremotes" ]; then
  echo "gdrive:         drive"
  echo "gdrive-chiffre: crypt"
  exit 0
fi
echo "$@" >> "{journal}"
exit 0
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
    (faux / "rclone").write_text(FAUX_RCLONE.format(journal=journal), encoding="utf-8")
    (faux / "rclone").chmod(0o755)

    (faux / "sqlite3").write_text(FAUX_SQLITE3, encoding="utf-8")
    (faux / "sqlite3").chmod(0o755)
    return tmp_path, base, journal, faux


def _lancer(atelier, **surcharges):
    tmp_path, base, journal, faux = atelier
    env = dict(os.environ)
    env["PATH"] = f"{faux}{os.pathsep}{env['PATH']}"
    env.update({"DB_PATH": str(base), "COMPRESS": "false",
                "REMOTE_URI": "gdrive-chiffre:sauvegardes"})
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
    assert envois[0].endswith("gdrive-chiffre:sauvegardes/archives"), envois[0]


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



# --- chiffrement ------------------------------------------------------------------
#
# Le .env porte la clé de session : avec elle et la base, déposées au même
# endroit, on peut se connecter en superadministrateur sans aucun mot de passe.
# Il ne part que vers une destination chiffrée.

def test_env_is_sent_to_an_encrypted_remote(atelier):
    resultat, copies = _lancer(atelier)
    assert resultat.returncode == 0, resultat.stderr
    assert any("env_" in c for c in copies)
    assert "Attention" not in resultat.stderr


def test_env_never_leaves_in_clear(atelier):
    """Une destination en clair — un réglage oublié — ne doit pas recevoir
    les secrets. La base part quand même, avec un avertissement : une
    sauvegarde en clair vaut mieux que pas de sauvegarde."""
    resultat, copies = _lancer(atelier, REMOTE_URI="gdrive:vehicules-backups")
    assert resultat.returncode == 0, resultat.stderr
    assert not any("env_" in c for c in copies), "le .env est parti en clair"
    assert any("vehicules_" in c for c in copies), "la base doit partir quand même"
    assert "n'est pas une destination chiffree" in resultat.stderr


def test_unknown_remote_is_treated_as_clear(atelier):
    resultat, copies = _lancer(atelier, REMOTE_URI="inconnu:dossier")
    assert not any("env_" in c for c in copies)


def test_works_without_optional_rclone_arguments(atelier):
    """Sans RCLONE_CONFIG ni compte de service, le tableau d'options est vide :
    bash avant 4.4 (macOS) échouait sous « set -u ». Relevé par l'audit."""
    resultat, _ = _lancer(atelier, RCLONE_CONFIG="", GDRIVE_SERVICE_ACCOUNT="")
    assert resultat.returncode == 0, resultat.stderr
