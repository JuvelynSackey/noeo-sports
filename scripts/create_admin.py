"""Bootstraps the very first ADMIN account (MASTER BUILD PROMPT section 54).

`POST /users` requires an ADMIN caller, so it can't create the first one —
this script talks to the database directly instead. Every subsequent user
(of any role) should be created through `POST /users` so the action is
audit-logged; this one, by construction, cannot be.

Usage:
    python scripts/create_admin.py --email admin@example.com
    (prompts are not supported non-interactively; pass the password via the
    ADMIN_BOOTSTRAP_PASSWORD env var to avoid it landing in shell history)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.base import SessionLocal
from app.database.models.audit import User
from app.database.models.enums import UserRole
from app.logging_config import configure_logging, get_logger
from app.services.auth import hash_password

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password",
        default=None,
        help="If omitted, read from the ADMIN_BOOTSTRAP_PASSWORD environment variable.",
    )
    args = parser.parse_args()

    password = args.password or os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
    if not password:
        parser.error("Provide --password or set ADMIN_BOOTSTRAP_PASSWORD")

    db = SessionLocal()
    try:
        existing = db.query(User).filter_by(email=args.email).first()
        if existing is not None:
            print(f"A user with email {args.email} already exists (role={existing.role}).")
            return

        user = User(email=args.email, hashed_password=hash_password(password), role=UserRole.ADMIN)
        db.add(user)
        db.commit()
        print(f"Created ADMIN user: {args.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
