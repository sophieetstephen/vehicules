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
    chef = User(name="Chef de centre", email="chef@csp.local", role=User.ROLE_ADMIN)
    chef.set_password("chef123")
    adj = User(name="Adjoint", email="adjoint@csp.local", role=User.ROLE_ADMIN)
    adj.set_password("adjoint123")
    per = User(name="Sapeur Dupont", email="dupont@csp.local", role=User.ROLE_USER)
    per.set_password("dupont123")
    super_admin = User(name="Super Admin", email="superadmin@csp.local", role=User.ROLE_SUPERADMIN)
    super_admin.set_password("superadmin123")
    db.session.add_all([chef, adj, per, super_admin])
    db.session.commit()

    print(
        "Init OK. Logins: chef@csp.local/chef123 adjoint@csp.local/adjoint123 dupont@csp.local/dupont123 superadmin@csp.local/superadmin123"
    )

