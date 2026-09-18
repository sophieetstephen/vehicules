"""Garde-fou : la suite de tests ne doit jamais toucher une base réelle.

Les tests appellent ``db.drop_all()``. Si l'application était connectée à
``instance/vehicules.db`` (ou à la base désignée par ``DATABASE_URL`` dans le
conteneur de production), lancer les tests effacerait toutes les données.
"""

from app import app
from models import db


def test_tests_use_in_memory_database():
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"
    with app.app_context():
        url = db.engine.url
        assert str(url) == "sqlite://", str(url)
        assert url.database in (None, "", ":memory:"), url.database
