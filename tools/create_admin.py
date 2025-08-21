#!/usr/bin/env python3
"""Promote or demote user accounts."""

import argparse
import os
import sys

# Ensure repository root is in import path
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app
from models import db, User


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
