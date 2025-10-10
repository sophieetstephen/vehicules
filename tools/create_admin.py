#!/usr/bin/env python3
"""Promote or demote user accounts."""

import argparse
import importlib
import os
import sys


def _load_app_and_models():
    """Return ``(app, db, User)`` after ensuring the repository root is importable."""

    root_dir = os.path.dirname(os.path.dirname(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    app_module = importlib.import_module("app")
    models_module = importlib.import_module("models")
    return app_module.app, models_module.db, models_module.User


app, db, User = _load_app_and_models()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote or demote a user by setting their role"
    )
    parser.add_argument("email", help="Email of the target user")
    parser.add_argument(
        "role",
        choices=[User.ROLE_SUPERADMIN, User.ROLE_ADMIN, User.ROLE_USER],
        help="Role to assign to the user",
    )
    args = parser.parse_args()

    with app.app_context():
        user = User.query.filter_by(email=args.email.lower()).first()
        if not user:
            print("User not found")
            return 1
        user.role = args.role
        db.session.commit()
        print(f"{user.email} is now '{user.role}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
