"""Create the demo operator/viewer accounts: cd /app/backend && python seed_users.py"""
import asyncio

from lib.auth import ensure_default_admin, hash_password
from lib.db import db
from models.auth import User

DEMO = [
    ("operator1", "Operator Gudang Siang", "operator", "operator123"),
    ("viewer1", "Pemantau Stok", "viewer", "viewer123"),
]


async def main() -> None:
    await ensure_default_admin()
    for username, full_name, role, password in DEMO:
        if await db.users.find_one({"username": username}):
            print(f"exists: {username}")
            continue
        password_hash, salt = hash_password(password)
        await db.users.insert_one(User(
            username=username, full_name=full_name, role=role,
            password_hash=password_hash, salt=salt,
        ).model_dump())
        print(f"created: {username} ({role})")


if __name__ == "__main__":
    asyncio.run(main())
