import importlib

from app import app

app_module = importlib.import_module("app")
from models import db, User


def test_register_sends_notification_to_superadmins(monkeypatch):
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SUPERADMIN_EMAILS"] = ["supercfg@example.com"]
    app.config["ADMIN_EMAILS"] = []

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

        existing_superadmin = User(
            name="Chief Admin",
            first_name="Chief",
            last_name="Admin",
            email="chief@example.com",
            role=User.ROLE_SUPERADMIN,
            status="active",
        )
        existing_superadmin.set_password("password123")
        db.session.add(existing_superadmin)
        db.session.commit()

        captured_calls = []

        def fake_send_mail(subject, body, to_addrs, *args, **kwargs):
            captured_calls.append(
                {
                    "subject": subject,
                    "body": body,
                    "recipients": list(to_addrs),
                }
            )
            return True, "sent"

        monkeypatch.setattr(app_module, "send_mail_msmtp", fake_send_mail)

        client = app.test_client()
        response = client.post(
            "/register",
            data={
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@example.com",
                "password": "strongpass",
                "password2": "strongpass",
            },
        )

        assert response.status_code == 302
        assert captured_calls, "A notification email should have been sent"
        notification = captured_calls[0]
        assert notification["subject"] == "Nouvelle demande de création de compte"
        assert sorted(notification["recipients"]) == [
            "chief@example.com",
            "supercfg@example.com",
        ]
        assert "john.doe@example.com" in notification["body"]

        db.drop_all()
