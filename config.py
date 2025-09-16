
import os


OWNER_SIGNATURE = "AS-2024-6f9e3c42"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY","change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL","sqlite:///vehicules.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    VEHICLE_ROLE_RULES = { "VL1": ["chef"], "VL2": ["chef","adjoint"] }
    MAIL_SERVER = os.environ.get("MAIL_SERVER","")
    MAIL_PORT = int(os.environ.get("MAIL_PORT","587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS","1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME","")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD","")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", os.environ.get("MAIL_USERNAME", "no-reply@csp.local")
    )
    SUPERADMIN_EMAILS = ["gestionvehiculestomer@gmail.com"]
    ADMIN_EMAILS = ["alexandre.stephen@free.fr"]
    SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "30"))
