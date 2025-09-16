from datetime import datetime, timedelta
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from models import User, db


def test_session_timeout_redirects_to_login_with_flash_message():
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SESSION_TIMEOUT_MINUTES"] = 1

    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

        user = User(
            name="Test User",
            first_name="Test",
            last_name="User",
            email="test@example.com",
            role=User.ROLE_USER,
            status="active",
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        client = app.test_client()

        login_resp = client.post(
            "/login",
            data={"email": "test@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert login_resp.status_code == 302

        with client.session_transaction() as sess:
            assert sess.get("uid") == user.id
            past_time = datetime.utcnow() - timedelta(
                minutes=app.config["SESSION_TIMEOUT_MINUTES"] + 1
            )
            sess["last_activity"] = past_time.isoformat()

        timeout_response = client.get("/home", follow_redirects=True)
        assert timeout_response.history, "Expected a redirect to occur"
        first_redirect = timeout_response.history[0]
        assert first_redirect.status_code == 302
        assert first_redirect.headers["Location"] == "/login"

        html = timeout_response.data.decode("utf-8")
        assert "Session expirée pour inactivité" in html

        db.session.remove()
        db.drop_all()
