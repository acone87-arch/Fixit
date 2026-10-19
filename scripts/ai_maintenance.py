"""Run with python -m scripts.ai_maintenance; default is a read-only preview."""
import argparse
import asyncio
import json


async def run(apply):
    from app.database import AsyncSessionLocal, engine
    from app.services.ai_retention import maintain
    try:
        async with AsyncSessionLocal() as db:
            print(json.dumps(await maintain(db, apply=apply)))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Clear AI result bodies older than seven days; keep ledger and repair links')
    args = parser.parse_args()
    asyncio.run(run(args.apply))
