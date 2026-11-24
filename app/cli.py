"""Local administrator bootstrap; no public API can grant this role."""

import argparse
import asyncio
import os
from getpass import getpass

from pydantic import ValidationError

from app.core.database import dispose_engine, get_session_factory
from app.core.exceptions import AppError
from app.models import User
from app.schemas import UserCreate
from app.services.users import register_user


async def create_admin(email: str, password: str, full_name: str = "") -> User:
    payload = UserCreate(email=email, password=password, full_name=full_name)
    async with get_session_factory()() as session:
        # Registration checks duplicates without promoting an existing account.
        return await register_user(session, payload, is_admin=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create-admin"])
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", default="")
    args = parser.parse_args()
    password = os.environ.get("ORDERFLOW_ADMIN_PASSWORD") or getpass("Admin password: ")
    try:
        await create_admin(args.email, password, args.full_name)
    except ValidationError:
        print("Invalid email, name or password (password must contain 8–128 characters).")
        return 1
    except AppError as exc:
        print(exc.message)
        return 1
    finally:
        await dispose_engine()
    print("Administrator created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
