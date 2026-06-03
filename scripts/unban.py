"""Script to manually unban an IP from the database."""

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/unban.py <ip>")
        sys.exit(1)

    ip = sys.argv[1]
    print(f"Unbanning IP: {ip}...")
    await db.init_db()
    await db.unban_ip(ip)
    print(f"IP {ip} successfully unbanned from the database.")
    print("Note: If the server is currently running, it will read the updated list on next restart, or you can trigger a reload.")


if __name__ == "__main__":
    asyncio.run(main())
