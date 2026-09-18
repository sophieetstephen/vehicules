
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


class NotificationSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    notify_superadmin = db.Column(db.Boolean, default=False)
    notify_admin = db.Column(db.Boolean, default=False)
    notify_user_ids = db.Column(db.JSON, default=list)
