
import os


OWNER_SIGNATURE = "AS-2024-6f9e3c42"


def _env_bool(name: str, default: bool = False) -> bool:
    """Return a boolean value from an environment variable.

    The previous implementation only recognised ``"1"`` as a truthy string which
    proved brittle in real deployments where values such as ``"true"`` or
    ``"yes"`` are commonly used.  Accept a broader range of canonical truthy
    representations while keeping backwards compatibility with integers and
    actual booleans.  Anything else is considered falsy so that accidental
    typos do not silently enable a feature.
    """

    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    normalized = str(raw_value).strip().lower()
    if not normalized:
        return False
    return normalized in {"1", "true", "t", "yes", "y", "on"}


def _get_secret_key() -> str:
    """Return SECRET_KEY from environment, or raise in production."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    # Allow insecure default only in development
    if os.environ.get("FLASK_ENV") == "development" or os.environ.get("FLASK_DEBUG"):
        return "dev-secret-insecure"
    raise RuntimeError(
        "SECRET_KEY must be set in production. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )


class Config:
    SECRET_KEY = _get_secret_key()
    WTF_CSRF_ENABLED = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///instance/vehicules.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    VEHICLE_ROLE_RULES = { "VL1": ["chef"], "VL2": ["chef","adjoint"] }
    MAIL_SERVER = os.environ.get("MAIL_SERVER","")
    MAIL_PORT = int(os.environ.get("MAIL_PORT","587"))
    MAIL_USE_TLS = _env_bool("MAIL_USE_TLS", True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME","")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD","")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", os.environ.get("MAIL_USERNAME", "no-reply@csp.local")
    )
    SUPERADMIN_EMAILS = ["gestionvehiculestomer@gmail.com"]
    ADMIN_EMAILS = ["alexandre.stephen@free.fr"]
    SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "30"))
