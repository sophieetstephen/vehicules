from getpass import getpass
from app import app, db, User
from models import Vehicle
from flask_migrate import upgrade


def demander_mot_de_passe(email):
    """Demande un mot de passe avec confirmation."""
    while True:
        mdp = getpass(f"  Mot de passe : ")
        if len(mdp) < 8:
            print("  ⚠ Le mot de passe doit contenir au moins 8 caractères.")
            continue
        mdp_confirm = getpass(f"  Confirmer : ")
        if mdp != mdp_confirm:
            print("  ⚠ Les mots de passe ne correspondent pas. Réessayez.")
            continue
        return mdp


with app.app_context():
    print("\n=== Initialisation de l'application ===\n")

    upgrade()

    # vehicles
    print("Création des véhicules...")
    data = [
        ("VL1", "Véhicule Léger 1 (Chef de centre)", 5),
        ("VL2", "Véhicule Léger 2 (Adjoint)", 5),
        ("VID2", "Véhicule d'Instruction Dép 2", 5),
        ("VIDXL", "Véhicule d'Instruction XL", 7),
        ("VRID", "Véhicule Rapide d'Intervention Dép", 5),
    ]
    for code, label, seats in data:
        db.session.add(Vehicle(code=code, label=label, seats=seats))
    print("✓ Véhicules créés\n")

    # users
    print("Compte Super Admin (gestionvehiculestomer@gmail.com)")
    mdp_super = demander_mot_de_passe("gestionvehiculestomer@gmail.com")
    super_admin = User(
        name="Super Admin",
        email="gestionvehiculestomer@gmail.com",
        role=User.ROLE_SUPERADMIN,
        status="active",
    )
    super_admin.set_password(mdp_super)
    print("✓ Compte Super Admin créé\n")

    print("Compte Admin (alexandre.stephen@free.fr)")
    mdp_admin = demander_mot_de_passe("alexandre.stephen@free.fr")
    admin = User(
        name="Administrateur",
        email="alexandre.stephen@free.fr",
        role=User.ROLE_ADMIN,
        status="active",
    )
    admin.set_password(mdp_admin)
    print("✓ Compte Admin créé\n")

    db.session.add_all([super_admin, admin])
    db.session.commit()

    print("=== Initialisation terminée ===\n")

