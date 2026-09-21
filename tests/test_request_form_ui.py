"""Ergonomie du formulaire de réservation.

Le champ « Avec qui » n'a de sens que si le covoiturage est coché, et le
formulaire s'étirait sur toute la largeur de l'écran sur ordinateur.
"""

import pytest

from app import app
from models import db, User


@pytest.fixture
def ctx():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield
        db.drop_all()


def _page(role=User.ROLE_USER):
    u = User(name="Dupont Jean", first_name="Jean", last_name="Dupont", username="dupontj",
             email="j@ex.fr", role=role, status="active", password_hash="x")
    db.session.add(u)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as s:
        s["uid"] = u.id
        s["pwd_stamp"] = u.session_stamp(app.config["SECRET_KEY"])
    return client.get("/request/new").data.decode()


def test_form_width_is_limited(ctx):
    assert "max-w-720" in _page()


def test_carpool_field_hidden_until_checked(ctx):
    html = _page()
    assert 'id="carpool_fields"' in html
    # Masqué au chargement...
    bloc = html.split('id="carpool_fields"')[1][:60]
    assert "d-none" in bloc
    # ...et rattaché à la case à cocher.
    assert "toggleCarpoolFields" in html
    assert "carpoolCheck.addEventListener('change', toggleCarpoolFields)" in html


def test_carpool_toggle_clears_selection(ctx):
    """Décocher le covoiturage doit vider les passagers déjà saisis."""
    html = _page()
    bascule = html.split("function toggleCarpoolFields()")[1].split("}")[0]
    assert "carpoolInput.value = ''" in bascule
    assert "selectedUsers = []" in bascule


def test_helper_texts_replace_the_old_standalone_hint(ctx):
    html = _page()
    assert html.count("Cochez pour") == 2, "une aide sous chaque case à cocher"
    assert "uniquement nécessaire pour les réservations" not in html


@pytest.mark.parametrize("role", [User.ROLE_USER, User.ROLE_ADMIN])
def test_form_still_complete_for_each_role(ctx, role):
    html = _page(role)
    for champ in ('name="start_date"', 'name="start_slot"', 'name="purpose"',
                  'name="carpool_with"', 'name="notes"'):
        assert champ in html, champ
    if role == User.ROLE_ADMIN:
        assert 'name="user_lookup"' in html
    else:
        assert 'name="first_name"' in html
