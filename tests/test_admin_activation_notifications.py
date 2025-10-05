import importlib
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app import app
from models import db, User

app_module = importlib.import_module("app")


def test_admin_activation_sends_notification(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

        admin = User(
            name="Admin User",
            first_name="Admin",
            last_name="User",
            email="admin@example.com",
            role=User.ROLE_ADMIN,
            status="active",
            password_hash="x",
        )
        db.session.add(admin)

        pending = User(
            name="Pending User",
            first_name="Pending",
            last_name="User",
            email="pending@example.com",
            role=User.ROLE_USER,
            status="pending",
            password_hash="x",
        )
        db.session.add(pending)
        db.session.commit()

        captured = {}

        def fake_send_mail(subject, body, to_addrs, *args, **kwargs):
            captured["subject"] = subject
            captured["body"] = body
            captured["to"] = to_addrs
            return True, "sent"

        monkeypatch.setattr(app_module, "send_mail_msmtp", fake_send_mail)

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["uid"] = admin.id

        response = client.get(f"/admin/activate/{pending.id}")
        assert response.status_code == 302

        refreshed = User.query.get(pending.id)
        assert refreshed.status == "active"

        assert captured, "An activation email should have been sent"
        assert "Votre compte est activé" in captured["subject"]
        assert "Votre compte est activé" in captured["body"]
        assert captured["to"] == pending.email

        db.drop_all()
