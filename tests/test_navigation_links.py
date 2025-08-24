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


@pytest.mark.parametrize('role', [User.ROLE_SUPERADMIN, User.ROLE_ADMIN, User.ROLE_USER])
def test_navbar_contains_only_home(role):
    html = _render(role)
    assert 'Accueil' in html
    assert 'Vue mensuelle' not in html
    assert 'Nouvelle demande' not in html
