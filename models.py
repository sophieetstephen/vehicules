
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
db = SQLAlchemy()

class User(db.Model):
    ROLE_SUPERADMIN = "superadmin"
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    first_name = db.Column(db.String(60), nullable=True)
    last_name = db.Column(db.String(60), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), default=ROLE_USER)
    password_hash = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default="pending")

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

    def generate_reset_token(self):
        """Return a signed token to reset the password."""
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        return s.dumps({"user_id": self.id})

    @staticmethod
    def verify_reset_token(token, max_age=3600):
        """Validate a reset token and return the associated user if valid."""
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            data = s.loads(token, max_age=max_age)
        except (BadSignature, SignatureExpired):
            return None
        return User.query.get(data.get("user_id"))

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
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending")  # pending/approved/rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
