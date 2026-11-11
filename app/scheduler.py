"""Background job: every morning, write today's affirmation and top up the offline bank.

Runs inside the web app (checks every 5 minutes). If you're offline it keeps retrying
until a backend is reachable, and the built-in affirmations cover the gap.
"""
import asyncio
import logging

from app import affirmations
from app.clock import now_local
from app.config import AFFIRMATION_HOUR
from app.db import Preference, SessionLocal
from app.llm import BackendUnavailable

log = logging.getLogger("pa.scheduler")
LAST_RUN_KEY = "_last_morning_run"


def morning_job(backends: list, force: bool = False) -> str:
    """Returns which backend did the work, or 'offline'."""
    now = now_local()
    with SessionLocal() as s:
        last = s.get(Preference, LAST_RUN_KEY)
        if not force and (now.hour < AFFIRMATION_HOUR or (last and last.value == now.date().isoformat())):
            return "skipped"
        for backend in backends:
            try:
                n = affirmations.refresh(s, backend)
            except BackendUnavailable:
                continue
            except Exception as e:  # bad JSON etc. — try again next tick
                log.warning("Affirmation refresh failed on %s: %s", backend.name, e)
                s.rollback()
                continue
            if last:
                last.value = now.date().isoformat()
            else:
                s.add(Preference(key=LAST_RUN_KEY, value=now.date().isoformat()))
            s.commit()
            log.info("Morning refresh via %s: %d affirmations written", backend.name, n)
            return backend.name
    return "offline"


async def run_forever(backends: list, every_seconds: int = 300):
    while True:
        try:
            await asyncio.to_thread(morning_job, backends)
        except Exception as e:
            log.warning("Scheduler error: %s", e)
        await asyncio.sleep(every_seconds)
