"""FastAPI web app: chat, today view, calendar, check-ins, and the UI."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from app import config, onboarding, scheduler, tools
from app.affirmations import get_for_date
from app.assistant import Assistant
from app.clock import parse_date, parse_dt, today_local
from app.db import (Affirmation, CheckIn, Conversation, Event, Memory,
                    Preference, SessionLocal, Task, init_db)
from app.llm import OllamaBackend

STATIC = Path(__file__).parent / "static"
assistant = Assistant()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    job = asyncio.create_task(scheduler.run_forever(assistant.backends))
    yield
    job.cancel()


app = FastAPI(title=f"{config.ASSISTANT_NAME} — Personal Assistant", lifespan=lifespan)


# --- helpers ---------------------------------------------------------------
def ev_json(e: Event) -> dict:
    return {"id": e.id, "title": e.title, "start": e.start.isoformat(timespec="minutes"),
            "end": e.end.isoformat(timespec="minutes"), "location": e.location, "notes": e.notes}


def aff_json(a: Affirmation) -> dict:
    return {"id": a.id, "text": a.text, "theme": a.theme, "rating": a.rating, "source": a.source}


# --- pages & status --------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {"assistant": config.ASSISTANT_NAME, "user": config.USER_NAME,
            "claude_configured": bool(config.ANTHROPIC_API_KEY),
            "ollama_available": OllamaBackend().available(),
            "last_mode": assistant.last_mode}


# --- chat --------------------------------------------------------------------
class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


@app.post("/api/chat")
def chat(body: ChatIn):
    with SessionLocal() as s:
        return assistant.chat(s, body.message, body.conversation_id)


@app.get("/api/conversations")
def conversations():
    with SessionLocal() as s:
        rows = s.scalars(select(Conversation).order_by(Conversation.id.desc()).limit(50)).all()
        return [{"id": c.id, "title": c.title} for c in rows]


@app.get("/api/conversations/{cid}")
def conversation(cid: int):
    with SessionLocal() as s:
        c = s.get(Conversation, cid)
        if not c:
            raise HTTPException(404)
        return {"id": c.id, "title": c.title, "messages": [{"role": m.role, "content": m.content} for m in c.messages]}


# --- today -----------------------------------------------------------------
@app.get("/api/today")
def today():
    with SessionLocal() as s:
        d = today_local()
        lo, hi = datetime.combine(d, datetime.min.time()), datetime.combine(d, datetime.max.time())
        events = s.scalars(select(Event).where(Event.start <= hi, Event.end >= lo).order_by(Event.start)).all()
        open_tasks = s.scalars(select(Task).where(Task.done.is_(False)).order_by(Task.id)).all()
        checkin = s.scalars(select(CheckIn).where(CheckIn.day == d).order_by(CheckIn.id.desc())).first()
        return {"date": d.isoformat(), "affirmation": aff_json(get_for_date(s, d)),
                "events": [ev_json(e) for e in events],
                "tasks": [{"id": t.id, "title": t.title, "due": t.due} for t in open_tasks],
                "checkin": {"mood": checkin.mood, "energy": checkin.energy, "note": checkin.note} if checkin else None,
                "onboarding": onboarding.status(s)}


class RateIn(BaseModel):
    rating: int


@app.post("/api/affirmations/{aid}/rate")
def rate(aid: int, body: RateIn):
    with SessionLocal() as s:
        return {"message": tools.rate_affirmation(s, aid, body.rating)}


@app.post("/api/affirmations/refresh")
def refresh_affirmations():
    """Manually run the morning job (handy for testing)."""
    return {"via": scheduler.morning_job(assistant.backends, force=True)}


class CheckInIn(BaseModel):
    mood: int
    energy: int | None = None
    note: str | None = None


@app.post("/api/checkin")
def checkin(body: CheckInIn):
    with SessionLocal() as s:
        return {"message": tools.log_checkin(s, body.mood, body.energy, body.note)}


# --- calendar ----------------------------------------------------------------
class EventIn(BaseModel):
    title: str
    start: str
    end: str | None = None
    location: str | None = None
    notes: str | None = None


class EventPatch(BaseModel):
    title: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    notes: str | None = None


@app.get("/api/events")
def events(start: str | None = None, end: str | None = None):
    d0 = parse_date(start)
    d1 = parse_date(end) if end else d0 + timedelta(days=6)
    lo, hi = datetime.combine(d0, datetime.min.time()), datetime.combine(d1, datetime.max.time())
    with SessionLocal() as s:
        rows = s.scalars(select(Event).where(Event.start <= hi, Event.end >= lo).order_by(Event.start)).all()
        return [ev_json(e) for e in rows]


@app.post("/api/events")
def create_event(body: EventIn):
    with SessionLocal() as s:
        try:
            parse_dt(body.start)
        except ValueError:
            raise HTTPException(400, "start must look like 2026-11-12 14:00")
        return {"message": tools.add_event(s, **body.model_dump())}


@app.patch("/api/events/{eid}")
def patch_event(eid: int, body: EventPatch):
    with SessionLocal() as s:
        return {"message": tools.update_event(s, eid, **body.model_dump())}


@app.delete("/api/events/{eid}")
def remove_event(eid: int):
    with SessionLocal() as s:
        return {"message": tools.delete_event(s, eid)}


# --- tasks, memory, preferences ------------------------------------------------
class TaskIn(BaseModel):
    title: str
    due: str | None = None


@app.get("/api/tasks")
def task_list():
    with SessionLocal() as s:
        return [{"id": t.id, "title": t.title, "due": t.due, "done": t.done}
                for t in s.scalars(select(Task).order_by(Task.id)).all()]


@app.post("/api/tasks")
def task_add(body: TaskIn):
    with SessionLocal() as s:
        return {"message": tools.add_task(s, body.title, body.due)}


@app.post("/api/tasks/{tid}/done")
def task_done(tid: int):
    with SessionLocal() as s:
        return {"message": tools.complete_task(s, tid)}


@app.get("/api/me")
def me():
    with SessionLocal() as s:
        prefs = s.scalars(select(Preference).where(~Preference.key.startswith("_")).order_by(Preference.key)).all()
        mems = s.scalars(select(Memory).order_by(Memory.id)).all()
        checkins = s.scalars(select(CheckIn).order_by(CheckIn.id.desc()).limit(14)).all()
        return {"onboarding": onboarding.status(s),
                "preferences": [{"key": p.key, "value": p.value} for p in prefs],
                "memories": [{"id": m.id, "category": m.category, "content": m.content} for m in mems],
                "checkins": [{"day": c.day.isoformat(), "mood": c.mood, "energy": c.energy, "note": c.note} for c in checkins]}


@app.delete("/api/memories/{mid}")
def memory_delete(mid: int):
    with SessionLocal() as s:
        return {"message": tools.forget(s, mid)}
