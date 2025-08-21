from app import app, db, User
from models import Vehicle


with app.app_context():
    db.drop_all()
    db.create_all()

    # vehicles
    data = [
        ("VL1", "Véhicule Léger 1 (Chef de centre)", 5),
        ("VL2", "Véhicule Léger 2 (Adjoint)", 5),
        ("VID2", "Véhicule d'Instruction Dép 2", 5),
        ("VIDXL", "Véhicule d'Instruction XL", 7),
        ("VRID", "Véhicule Rapide d'Intervention Dép", 5),
    ]
    for c, l, s in data:
        db.session.add(Vehicle(code=c, label=l, seats=s))

    # users
    super_admin = User(
        name="Super Admin",
        email="gestionvehiculestomer@gmail.com",
        role=User.ROLE_SUPERADMIN,
    )
    super_admin.set_password("Sophieestaires59940")
    admin = User(
        name="Administrateur",
        email="alexandre.stephen@free.fr",
        role=User.ROLE_ADMIN,
    )
    admin.set_password("Sophieestaires")
    db.session.add_all([super_admin, admin])
    db.session.commit()

    print(
        "Init OK. Users: gestionvehiculestomer@gmail.com, alexandre.stephen@free.fr"
    )

