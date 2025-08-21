
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
db = SQLAlchemy()

class User(db.Model):
    ROLE_SUPERADMIN = "superadmin"
    ROLE_ADMIN = "admin"
    ROLE_USER = "user"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), default=ROLE_USER)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    seats = db.Column(db.Integer, default=5)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=True)  # peut etre non attribuee au depart
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime, nullable=False)
    purpose = db.Column(db.String(200), nullable=True)
    carpool = db.Column(db.Boolean, default=False)
    carpool_with = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending")  # pending/approved/rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vehicle = db.relationship("Vehicle", backref="reservations")
    user = db.relationship("User", backref="reservations")
