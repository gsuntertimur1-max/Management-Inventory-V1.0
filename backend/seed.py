"""Standalone seeder: cd /app/backend && python seed.py"""
import asyncio

from lib.seeder import run_seed


async def main() -> None:
    counts = await run_seed()
    print(f"seeded: {counts}")


if __name__ == "__main__":
    asyncio.run(main())
