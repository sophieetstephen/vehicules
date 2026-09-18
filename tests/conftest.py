"""Configuration commune des tests.

Chargé automatiquement par pytest avant les tests :

* fournit une ``SECRET_KEY`` (obligatoire en production, l'import de ``app``
  échouerait sinon) ;
* pointe le serveur SMTP vers un port local fermé pour que les tests qui ne
  simulent pas l'envoi de mail échouent immédiatement au lieu d'attendre un
  délai réseau vers Gmail.
"""

import os
import sys

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("MAIL_SERVER", "127.0.0.1")
os.environ.setdefault("MAIL_PORT", "9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
