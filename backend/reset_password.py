"""Password recovery from the pod, for when nobody can log in.

Usage:
  cd /app/backend && python reset_password.py <username> <new_password>
  cd /app/backend && python reset_password.py --list
"""
import asyncio
import sys

from lib.auth import hash_password
from lib.db import db


async def show_users() -> None:
    print("Akun terdaftar:")
    async for u in db.users.find().sort("username", 1):
        print(f"  - {u['username']:<16} role={u['role']:<9} nama={u.get('full_name', '')}")


async def reset(username: str, password: str) -> None:
    uname = username.strip().lower()
    user = await db.users.find_one({"username": uname})
    if not user:
        print(f"Akun '{uname}' tidak ditemukan.")
        await show_users()
        return
    password_hash, salt = hash_password(password)
    await db.users.update_one(
        {"id": user["id"]}, {"$set": {"password_hash": password_hash, "salt": salt}}
    )
    await db.sessions.delete_many({"user_id": user["id"]})
    print(f"Password '{uname}' berhasil direset. Sesi lama dihapus.")


async def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] == "--list":
        await show_users()
        return
    if len(args) < 2:
        print(__doc__)
        return
    await reset(args[0], args[1])


if __name__ == "__main__":
    asyncio.run(main())
