"""Explicit maintenance: clear expired result bodies, retain accounting/tombstones."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, null, select, update
from app.models.ai import AIGeneration


async def maintain(db, *, apply=False, now=None):
    now = now or datetime.now(timezone.utc)
    expired = (AIGeneration.created_at < now - timedelta(days=7), func.jsonb_typeof(AIGeneration.result_json) == "object")
    results = await db.scalar(select(func.count()).select_from(AIGeneration).where(*expired))
    old = await db.scalar(select(func.count()).select_from(AIGeneration).where(
        AIGeneration.created_at < now - timedelta(days=90)))
    if apply:
        await db.execute(update(AIGeneration).where(*expired).values(result_json=null()))
        await db.commit()
    return {"mode": "apply" if apply else "dry_run", "expired_result_bodies": results,
            "metadata_older_than_90_days": old, "metadata_deleted": 0,
            "accounting_and_operation_ids_preserved": True}
