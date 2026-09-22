"""Les fichiers de service livrés doivent décrire une installation réelle.

Deux pertes de temps ont eu la même cause : un nom qui ne correspondait à rien.
``tools/archive_year.py`` importait de ``app`` un nom inexistant, et le service
de sauvegarde était cherché sous ``backup-db`` alors qu'il est installé sous
``vehicules-backup``. Ces tests lisent les fichiers d'unité et vérifient que ce
qu'ils désignent existe.
"""

import pathlib
import re

import pytest

TOOLS = pathlib.Path("tools")
SERVICES = sorted(TOOLS.glob("*.service"))
TIMERS = sorted(TOOLS.glob("*.timer"))
README = pathlib.Path("README.md").read_text(encoding="utf-8")


def _directive(fichier, nom):
    """Valeur d'une directive systemd, ou None."""
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne.startswith(f"{nom}="):
            return ligne.split("=", 1)[1].strip()
    return None


@pytest.mark.parametrize("service", SERVICES, ids=lambda f: f.name)
def test_service_points_at_a_file_that_exists(service):
    """Un ExecStart qui nomme un script absent échoue à l'exécution, des mois
    plus tard, sans que personne ne regarde."""
    commande = _directive(service, "ExecStart")
    assert commande, f"{service.name} : pas d'ExecStart"

    vises = [mot for mot in commande.split() if "tools/" in mot]
    assert vises, f"{service.name} : aucun script du dépôt dans ExecStart"
    for cible in vises:
        chemin = pathlib.Path(cible[cible.index("tools/"):])
        assert chemin.exists(), f"{service.name} désigne {chemin}, absent du dépôt"


@pytest.mark.parametrize("timer", TIMERS, ids=lambda f: f.name)
def test_timer_has_a_matching_service(timer):
    """Sans directive ``Unit=``, systemd cherche le service de même nom : un
    minuteur seul ne déclenche rien."""
    explicite = _directive(timer, "Unit")
    attendu = explicite or f"{timer.stem}.service"
    assert (TOOLS / attendu).exists(), f"{timer.name} attend {attendu}, absent de tools/"


@pytest.mark.parametrize("timer", TIMERS, ids=lambda f: f.name)
def test_timer_is_scheduled_and_catches_up(timer):
    """``Persistent`` rattrape une exécution manquée pendant une coupure."""
    texte = timer.read_text(encoding="utf-8")
    assert "OnCalendar=" in texte, f"{timer.name} : aucune échéance"
    assert "Persistent=true" in texte, f"{timer.name} : une coupure ferait sauter le tour"


def test_backup_unit_is_named_as_installed():
    """Le service tourne sur le Raspberry sous le nom « vehicules-backup » :
    livrer le modèle sous un autre nom envoyait chercher une unité inexistante.
    """
    assert (TOOLS / "vehicules-backup.service").exists()
    assert (TOOLS / "vehicules-backup.timer").exists()
    assert not (TOOLS / "backup_db.service").exists(), "ancien nom encore présent"


def test_readme_explains_how_to_install_the_units():
    """Le README disait comment les configurer, jamais comment les installer —
    d'où un minuteur de sauvegarde absent de systemd."""
    assert "/etc/systemd/system/" in README
    assert "systemctl daemon-reload" in README
    assert "systemctl enable --now vehicules-backup.timer" in README


def test_readme_names_the_units_it_ships():
    """Un nom cité dans la documentation et introuvable dans tools/ fait
    chercher au mauvais endroit."""
    cites = set(re.findall(r"tools/([\w.-]+\.(?:service|timer))", README))
    manquants = [nom for nom in cites if not (TOOLS / nom).exists()]
    assert not manquants, f"cités dans le README mais absents : {manquants}"


def test_backup_service_runs_as_the_application_user():
    """Lancé en root, rclone réécrit sa configuration en root et les
    sauvegardes manuelles échouent ensuite."""
    service = TOOLS / "vehicules-backup.service"
    assert _directive(service, "User") == "pi"
    assert _directive(service, "Group") == "pi"


def test_annual_archive_never_purges_from_the_timer():
    """Le 31 décembre ne doit pas supprimer de réservations."""
    commande = _directive(TOOLS / "archive_year.service", "ExecStart")
    assert "--purge" not in commande, commande


# Interpreteurs admis : ceux qui existent sur n'importe quelle installation.
# Un chemin de venv fige la machine sur laquelle le fichier a ete ecrit.
LANCEURS = ("/usr/bin/docker", "/usr/bin/env", "/usr/bin/python3", "/bin/sh")


@pytest.mark.parametrize("service", SERVICES, ids=lambda f: f.name)
def test_service_does_not_hardcode_a_foreign_path(service):
    """archive_reservations.service pointait vers /workspace/vehicules/venv :
    le chemin d'une autre machine, donc un échec à la première exécution."""
    commande = _directive(service, "ExecStart")
    lanceur = commande.split()[0]
    assert lanceur.startswith(LANCEURS), f"{service.name} : lanceur {lanceur}"

    travail = _directive(service, "WorkingDirectory")
    if travail:
        assert travail.startswith("/opt/vehicules/"), (
            f"{service.name} : WorkingDirectory {travail} hors de l'installation"
        )
