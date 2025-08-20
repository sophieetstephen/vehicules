
from app import app, db, User
from models import Vehicle
with app.app_context():
    db.drop_all(); db.create_all()
    # vehicles
    data=[("VL1","Véhicule Léger 1 (Chef de centre)",5),
          ("VL2","Véhicule Léger 2 (Adjoint)",5),
          ("VID2","Véhicule d'Instruction Dép 2",5),
          ("VIDXL","Véhicule d'Instruction XL",7),
          ("VRID","Véhicule Rapide d'Intervention Dép",5)]
    for c,l,s in data:
        db.session.add(Vehicle(code=c,label=l,seats=s))
    # users
    chef=User(name="Chef de centre", email="chef@csp.local", role="chef"); chef.set_password("chef123")
    adj=User(name="Adjoint", email="adjoint@csp.local", role="adjoint"); adj.set_password("adjoint123")
    per=User(name="Sapeur Dupont", email="dupont@csp.local", role="personnel"); per.set_password("dupont123")
    db.session.add_all([chef,adj,per]); db.session.commit()

    admin = User(
        name="Alexandre Stephen",
        email="GestionVehiculeStomer@gmail.com".lower(),
        role="admin",
    )
    admin.set_password("Sophieestaires59940")
    db.session.add(admin)
    db.session.commit()
    print(
        "Init OK. Logins: chef@csp.local/chef123 adjoint@csp.local/adjoint123 dupont@csp.local/dupont123 admin: GestionVehiculeStomer@gmail.com/Sophieestaires59940"
    )
