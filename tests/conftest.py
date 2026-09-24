"""Configuration commune des tests.

Chargé automatiquement par pytest avant les tests :

* force une base SQLite **en mémoire** : les tests font ``drop_all()`` et ne
  doivent jamais toucher ``instance/vehicules.db`` ni la base désignée par
  ``DATABASE_URL`` (cas du conteneur Docker en production) ;
* fournit une ``SECRET_KEY`` (obligatoire en production, l'import de ``app``
  échouerait sinon) ;
* pointe le serveur SMTP vers un port local fermé pour que les tests qui ne
  simulent pas l'envoi de mail échouent immédiatement au lieu d'attendre un
  délai réseau vers Gmail.

Ces variables sont lues par ``config.py`` à l'import de ``app`` : elles doivent
donc être positionnées ici, avant tout import de l'application.
"""

import os
import sys

# Toujours écrasé, jamais ``setdefault`` : un DATABASE_URL de production hérité
# de l'environnement du conteneur ne doit pas atteindre les tests.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ["MAIL_SERVER"] = "127.0.0.1"
os.environ["MAIL_PORT"] = "9"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import tempfile

import pytest


@pytest.fixture(autouse=True)
def _etat_mail_isole(tmp_path_factory):
    """Chaque test a son propre fichier d'état de l'envoi des e-mails.

    Sans cela, les tests écrivent dans ``instance/mail_health.json`` — le
    dossier réel de l'application — et un état laissé par l'un fait échouer un
    autre selon l'ordre d'exécution.
    """

    from app import app

    dossier = tmp_path_factory.mktemp("mail-health")
    ancien = app.config.get("MAIL_HEALTH_PATH")
    app.config["MAIL_HEALTH_PATH"] = str(dossier / "mail_health.json")
    try:
        yield
    finally:
        app.config["MAIL_HEALTH_PATH"] = ancien
