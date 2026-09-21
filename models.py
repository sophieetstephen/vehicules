
import hashlib
import hmac
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from utils import build_username_base, generate_password, make_unique_username
db = SQLAlchemy()

class User(db.Model):
    ROLE_SUPERADMIN = "superadmin"
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    first_name = db.Column(db.String(60), nullable=True)
    last_name = db.Column(db.String(60), nullable=True)
    # Identifiant de connexion (nom + initiale du prénom, ex: "dupontj").
    # L'adresse e-mail ne sert plus qu'aux notifications.
    username = db.Column(db.String(60), unique=True, nullable=True, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), default=ROLE_USER)
    password_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="pending")

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def session_stamp(self, secret_key):
        """Empreinte du mot de passe courant, à comparer à celle de la session.

        Permet d'invalider les sessions déjà ouvertes dès qu'un mot de passe est
        régénéré. C'est un HMAC : la valeur déposée dans le cookie ne révèle
        rien du hachage sans la clé secrète du serveur.
        """

        return hmac.new(
            str(secret_key).encode(),
            (self.password_hash or "").encode(),
            hashlib.sha256,
        ).hexdigest()[:16]

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

    def set_random_password(self):
        """Assign a freshly generated password and return it in clear text.

        The clear text value is only returned so that it can be shown once to
        the administrator and e-mailed to the user; it is never stored.
        """

        password = generate_password()
        self.set_password(password)
        return password

    @staticmethod
    def username_taken(candidate, exclude_id=None):
        query = User.query.filter(User.username == candidate)
        if exclude_id is not None:
            query = query.filter(User.id != exclude_id)
        return query.first() is not None

    def assign_username(self):
        """Compute and set a unique login identifier for this user."""

        base = build_username_base(
            first_name=self.first_name,
            last_name=self.last_name,
            name=self.name,
            email=self.email,
        )
        self.username = make_unique_username(
            base, lambda c: User.username_taken(c, exclude_id=self.id)
        )
        return self.username

    @staticmethod
    def find_by_login(identifier):
        """Return the user matching a login identifier (case-insensitive)."""

        if not identifier:
            return None
        return User.query.filter(User.username == identifier.strip().lower()).first()

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    seats = db.Column(db.Integer, default=5)
    category = db.Column(db.String(50), nullable=True)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)  # peut etre non attribuee au depart
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(200), nullable=True)
    carpool = db.Column(db.Boolean, default=False)
    carpool_with = db.Column(db.String(200), nullable=True)
    carpool_with_ids = db.Column(db.JSON, default=list)
    carpool_with_details = db.Column(db.JSON, default=list)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending")  # pending/approved/rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    archived_at = db.Column(db.DateTime, nullable=True)

    vehicle = db.relationship("Vehicle", backref="reservations")
    user = db.relationship("User", backref="reservations")
    segments = db.relationship(
        "ReservationSegment",
        back_populates="reservation",
        cascade="all, delete-orphan",
    )


class ReservationSegment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(
        db.Integer, db.ForeignKey('reservation.id'), nullable=False
    )
    vehicle_id = db.Column(
        db.Integer, db.ForeignKey('vehicle.id'), nullable=False
    )
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)

    reservation = db.relationship("Reservation", back_populates="segments")
    vehicle = db.relationship("Vehicle")


class VehicleUnavailability(db.Model):
    """Période pendant laquelle un véhicule ne peut pas être attribué.

    ``end_at`` à ``None`` signifie « jusqu'à nouvel ordre ».
    """

    CATEGORIES = [
        ("mecanique", "Panne mécanique"),
        ("entretien", "Entretien / contrôle technique"),
        ("carrosserie", "Carrosserie"),
        ("autre", "Autre"),
    ]

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=True)
    category = db.Column(db.String(30), nullable=False, default="mecanique")
    details = db.Column(db.String(200), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vehicle = db.relationship(
        "Vehicle",
        backref=db.backref("unavailabilities", cascade="all, delete-orphan"),
    )
    creator = db.relationship("User")

    @property
    def category_label(self):
        return dict(self.CATEGORIES).get(self.category, self.category or "")

    @property
    def label(self):
        base = self.category_label
        if self.details:
            return f"{base} – {self.details}"
        return base

    def covers(self, start, end):
        """True if the unavailability overlaps the ``[start, end)`` window."""

        if self.start_at >= end:
            return False
        return self.end_at is None or self.end_at > start

    def is_active_at(self, moment):
        return self.start_at <= moment and (self.end_at is None or self.end_at > moment)


class CredentialHandoff(db.Model):
    """Identifiants fraîchement générés, en attente d'affichage à l'administrateur.

    Le mot de passe en clair ne doit **pas** transiter par le cookie de session :
    celui-ci part chez le navigateur et peut y être conservé. Il est donc gardé
    côté serveur le temps d'une redirection, la session ne portant qu'un jeton
    opaque. La ligne est supprimée dès l'affichage, et de toute façon au bout de
    ``MAX_AGE_MINUTES``.
    """

    MAX_AGE_MINUTES = 10

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    password = db.Column(db.String(64), nullable=False)
    regenerated = db.Column(db.Boolean, nullable=False, default=False)
    mail_sent = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User")


class LoginAttempt(db.Model):
    """Tentative de connexion, réussie ou non.

    Sert à limiter les tentatives (blocage temporaire après plusieurs échecs)
    et fournit un historique consultable des connexions échouées.
    """

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), nullable=False, index=True)
    ip = db.Column(db.String(45), nullable=True, index=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class NotificationSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    notify_superadmin = db.Column(db.Boolean, default=False)
    notify_admin = db.Column(db.Boolean, default=False)
    notify_user_ids = db.Column(db.JSON, default=list)
