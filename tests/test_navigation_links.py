import os
import sys

import pytest
from flask import render_template

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from models import User


def _render_nav(role: str) -> str:
    with app.test_request_context('/'):
        user = User(
            name='Test User',
            first_name='Test',
            last_name='User',
            email='test@example.com',
            role=role,
            password_hash='x',
        )
        return render_template('base.html', user=user)


@pytest.mark.parametrize('role', [User.ROLE_SUPERADMIN, User.ROLE_ADMIN, User.ROLE_USER])
def test_links_hidden_for_superadmin(role):
    html = _render_nav(role)
    assert 'Accueil' in html
    assert 'Planning mensuel' not in html
    assert 'Nouvelle demande' not in html


def _render_home(role: str) -> str:
    templates = {
        User.ROLE_SUPERADMIN: 'superadmin_home.html',
        User.ROLE_ADMIN: 'admin_home.html',
        User.ROLE_USER: 'user_home.html',
    }
    with app.test_request_context('/'):
        user = User(
            name='Test User',
            first_name='Test',
            last_name='User',
            email='test@example.com',
            role=role,
            password_hash='x',
        )
        return render_template(templates[role], user=user, current_user=user)


@pytest.mark.parametrize(
    'role,links',
    [
        (User.ROLE_USER, ['Planning mensuel', 'Nouvelle demande', 'Contact']),
        (
            User.ROLE_ADMIN,
            ['Gestion du parc', 'Gestion des réservations', 'Planning mensuel', 'Nouvelle demande'],
        ),
        (
            User.ROLE_SUPERADMIN,
            [
                'Gestion des utilisateurs',
                'Gestion du parc',
                'Gestion des réservations',
                'Gestion des congés',
                'Planning mensuel',
                'Nouvelle demande',
            ],
        ),
    ],
)
def test_home_tabs_by_role(role, links):
    html = _render_home(role)
    for link in links:
        assert link in html
    assert html.count('list-group-item-action') == len(links)
