import os
import sys

import pytest
from flask import render_template

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from models import User


def _render(role: str) -> str:
    with app.test_request_context('/'):
        user = User(name='Test', email='test@example.com', role=role, password_hash='x')
        return render_template('base.html', user=user)


def test_links_hidden_for_superadmin():
    html = _render(User.ROLE_SUPERADMIN)
    assert 'Vue mensuelle' not in html
    assert 'Nouvelle demande' not in html
    assert 'Accueil' in html


@pytest.mark.parametrize('role', [User.ROLE_ADMIN, User.ROLE_USER])
def test_links_visible_for_other_roles(role):
    html = _render(role)
    assert 'Vue mensuelle' in html
    assert 'Nouvelle demande' in html
    assert 'Accueil' in html
