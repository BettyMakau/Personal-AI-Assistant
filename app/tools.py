"""Tools the assistant can call.

Add a new tool by:
1. writing a function `def my_tool(session, **kwargs) -> str`
2. adding its JSON schema to TOOL_SCHEMAS
3. registering it in TOOL_FUNCTIONS
"""
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.clock import fmt_dt, now_local, parse_date, parse_dt, today_local
from app.config import TIMEZONE
from app.db import Affirmation, CheckIn, Event, Memory, Preference, Task
from app import onboarding


# --- Time ----------------------------------------------------------------
def get_current_time(session: Session) -> str:
    return now_local().strftime(f"%A %d %B %Y, %H:%M ({TIMEZONE})")


# --- Memory & preferences ---------------------------------------------------
def remember(session: Session, content: str, category: str = "general") -> str:
    m = Memory(content=content, category=category)
    session.add(m)
    session.commit()
    return f"Saved memory #{m.id}."


def search_memory(session: Session, query: str) -> str:
    words = [w for w in query.split() if len(w) > 2] or [query]
    stmt = select(Memory).where(or_(*[Memory.content.ilike(f"%{w}%") for w in words])).limit(10)
    rows = session.scalars(stmt).all()
    return "\n".join(f"#{m.id} [{m.category}] {m.content}" for m in rows) or "No matching memories."


def forget(session: Session, memory_id: int) -> str:
    m = session.get(Memory, memory_id)
    if not m:
        return f"No memory #{memory_id}."
    session.delete(m)
    session.commit()
    return f"Deleted memory #{memory_id}."


def set_preference(session: Session, key: str, value: str) -> str:
    key = key.strip().lower().replace(" ", "_")
    p = session.get(Preference, key)
    if p:
        p.value = value
    else:
        session.add(Preference(key=key, value=value))
    session.commit()
    return f"Preference saved: {key} = {value}"


def get_preferences(session: Session) -> str:
    rows = session.scalars(select(Preference).where(~Preference.key.startswith("_")).order_by(Preference.key)).all()
    return "\n".join(f"{p.key}: {p.value}" for p in rows) or "No preferences yet."


def complete_onboarding(session: Session, summary: str) -> str:
    p = onboarding.get_profile(session)
    p.onboarding_completed, p.summary = True, summary
    session.commit()
    return "Learning period marked complete; profile summary saved."


def log_checkin(session: Session, mood: int, energy: int | None = None, note: str | None = None) -> str:
    session.add(CheckIn(day=today_local(), mood=int(mood), energy=energy, note=note))
    session.commit()
    return f"Check-in logged (mood {mood}/5" + (f", energy {energy}/5" if energy else "") + ")."


# --- Tasks ---------------------------------------------------------------
def add_task(session: Session, title: str, due: str | None = None) -> str:
    t = Task(title=title, due=due)
    session.add(t)
    session.commit()
    return f"Added task #{t.id}: {title}" + (f" (due {due})" if due else "")


def list_tasks(session: Session, include_done: bool = False) -> str:
    stmt = select(Task).order_by(Task.id)
    if not include_done:
        stmt = stmt.where(Task.done.is_(False))
    rows = session.scalars(stmt).all()
    return "\n".join(f"#{t.id} [{'x' if t.done else ' '}] {t.title}" + (f" — due {t.due}" if t.due else "")
                     for t in rows) or "No tasks."


def complete_task(session: Session, task_id: int) -> str:
    t = session.get(Task, task_id)
    if not t:
        return f"No task #{task_id}."
    t.done = True
    session.commit()
    return f"Marked task #{task_id} done."


# --- Calendar ------------------------------------------------------------
def _overlaps(session: Session, start: datetime, end: datetime, ignore_id: int | None = None) -> list[Event]:
    stmt = select(Event).where(Event.start < end, Event.end > start)
    if ignore_id:
        stmt = stmt.where(Event.id != ignore_id)
    return list(session.scalars(stmt).all())


def _event_line(e: Event) -> str:
    extra = f" @ {e.location}" if e.location else ""
    return f"#{e.id} {fmt_dt(e.start)}–{e.end.strftime('%H:%M')} {e.title}{extra}"


def add_event(session: Session, title: str, start: str, end: str | None = None,
              location: str | None = None, notes: str | None = None) -> str:
    s = parse_dt(start)
    e_ = parse_dt(end) if end else s + timedelta(hours=1)
    if e_ <= s:
        return "End time must be after start time."
    clashes = _overlaps(session, s, e_)
    ev = Event(title=title, start=s, end=e_, location=location, notes=notes)
    session.add(ev)
    session.commit()
    msg = f"Added event {_event_line(ev)}"
    if clashes:
        msg += "\nHeads-up, it overlaps with: " + "; ".join(_event_line(c) for c in clashes)
    return msg


def list_events(session: Session, start_date: str | None = None, end_date: str | None = None) -> str:
    d0 = parse_date(start_date)
    d1 = parse_date(end_date) if end_date else d0 + timedelta(days=6)
    lo, hi = datetime.combine(d0, datetime.min.time()), datetime.combine(d1, datetime.max.time())
    rows = session.scalars(select(Event).where(Event.start <= hi, Event.end >= lo).order_by(Event.start)).all()
    return "\n".join(_event_line(e) for e in rows) or f"No events between {d0} and {d1}."


def update_event(session: Session, event_id: int, title: str | None = None, start: str | None = None,
                 end: str | None = None, location: str | None = None, notes: str | None = None) -> str:
    ev = session.get(Event, event_id)
    if not ev:
        return f"No event #{event_id}."
    if start:
        length = ev.end - ev.start
        ev.start = parse_dt(start)
        ev.end = parse_dt(end) if end else ev.start + length  # moving keeps the duration
    elif end:
        ev.end = parse_dt(end)
    for field, val in (("title", title), ("location", location), ("notes", notes)):
        if val is not None:
            setattr(ev, field, val)
    if ev.end <= ev.start:
        session.rollback()
        return "End time must be after start time."
    session.commit()
    clashes = _overlaps(session, ev.start, ev.end, ev.id)
    msg = f"Updated {_event_line(ev)}"
    return msg + ("\nOverlaps with: " + "; ".join(_event_line(c) for c in clashes) if clashes else "")


def delete_event(session: Session, event_id: int) -> str:
    ev = session.get(Event, event_id)
    if not ev:
        return f"No event #{event_id}."
    session.delete(ev)
    session.commit()
    return f"Deleted event #{event_id}."


def _pref(session: Session, key: str, default: str) -> str:
    p = session.get(Preference, key)
    return p.value if p else default


def find_free_time(session: Session, date: str | None = None, duration_minutes: int = 60) -> str:
    """Free slots inside working hours (from preferences) on a given day."""
    d = parse_date(date)
    try:
        ws = datetime.combine(d, datetime.strptime(_pref(session, "work_start", "08:00"), "%H:%M").time())
        we = datetime.combine(d, datetime.strptime(_pref(session, "work_end", "17:00"), "%H:%M").time())
    except ValueError:
        ws, we = datetime.combine(d, datetime.min.time()).replace(hour=8), datetime.combine(d, datetime.min.time()).replace(hour=17)
    if d == today_local():
        ws = max(ws, now_local())
    busy = sorted(_overlaps(session, ws, we), key=lambda e: e.start)
    slots, cursor, need = [], ws, timedelta(minutes=duration_minutes)
    for e in busy:
        if e.start - cursor >= need:
            slots.append((cursor, e.start))
        cursor = max(cursor, e.end)
    if we - cursor >= need:
        slots.append((cursor, we))
    if not slots:
        return f"No free {duration_minutes}-minute slot on {d} within working hours."
    return "\n".join(f"{a.strftime('%H:%M')}–{b.strftime('%H:%M')}" for a, b in slots)


def get_day_overview(session: Session, date: str | None = None) -> str:
    """Everything needed to plan a day: events, tasks, preferences, last check-in."""
    from app.affirmations import get_for_date  # local import avoids a cycle
    d = parse_date(date)
    events = list_events(session, d.isoformat(), d.isoformat())
    tasks = list_tasks(session)
    last = session.scalars(select(CheckIn).order_by(CheckIn.id.desc()).limit(1)).first()
    checkin = f"mood {last.mood}/5, energy {last.energy or '?'}/5 on {last.day} — {last.note or ''}" if last else "none yet"
    aff = get_for_date(session, d)
    return (f"Date: {d:%A %d %B %Y}\nEvents:\n{events}\nOpen tasks:\n{tasks}\n"
            f"Free time (1h+):\n{find_free_time(session, d.isoformat(), 60)}\n"
            f"Last check-in: {checkin}\nAffirmation: {aff.text}\nPreferences:\n{get_preferences(session)}")


# --- Affirmations ---------------------------------------------------------
def get_today_affirmation(session: Session) -> str:
    from app.affirmations import get_for_date
    a = get_for_date(session, today_local())
    return f"#{a.id} ({a.theme or 'general'}): {a.text}"


def rate_affirmation(session: Session, affirmation_id: int, rating: int) -> str:
    a = session.get(Affirmation, affirmation_id)
    if not a:
        return f"No affirmation #{affirmation_id}."
    a.rating = max(1, min(5, int(rating)))
    session.commit()
    return f"Thanks — rated {a.rating}/5. Future affirmations will adapt."


# --- Registry --------------------------------------------------------------
def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, **({"required": required} if required else {})}


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
DT = {"type": "string", "description": "Local date-time 'YYYY-MM-DD HH:MM'"}
D = {"type": "string", "description": "Date 'YYYY-MM-DD' (default today)"}

TOOL_SCHEMAS = [
    {"name": "get_current_time", "description": "Current local date and time.", "input_schema": _obj({})},
    {"name": "remember", "description": "Save a free-form fact about the user to long-term memory.",
     "input_schema": _obj({"content": S, "category": {"type": "string", "description": "preference, person, project, routine, general"}}, ["content"])},
    {"name": "search_memory", "description": "Search long-term memory.", "input_schema": _obj({"query": S}, ["query"])},
    {"name": "forget", "description": "Delete a memory by id.", "input_schema": _obj({"memory_id": I}, ["memory_id"])},
    {"name": "set_preference", "description": "Save or update a structured preference (e.g. wake_time, work_start, work_end, goals, affirmation_tone, planning_style).",
     "input_schema": _obj({"key": S, "value": S}, ["key", "value"])},
    {"name": "get_preferences", "description": "List all known preferences.", "input_schema": _obj({})},
    {"name": "log_checkin", "description": "Log how the user is doing today.",
     "input_schema": _obj({"mood": {"type": "integer", "description": "1-5"}, "energy": {"type": "integer", "description": "1-5"}, "note": S}, ["mood"])},
    {"name": "complete_onboarding", "description": "Finish the learning period once the user confirms their profile summary.",
     "input_schema": _obj({"summary": S}, ["summary"])},
    {"name": "add_task", "description": "Add a to-do item.", "input_schema": _obj({"title": S, "due": D}, ["title"])},
    {"name": "list_tasks", "description": "List tasks.", "input_schema": _obj({"include_done": B})},
    {"name": "complete_task", "description": "Mark a task done.", "input_schema": _obj({"task_id": I}, ["task_id"])},
    {"name": "add_event", "description": "Add an event to the built-in calendar. Warns about overlaps. Default length 1 hour.",
     "input_schema": _obj({"title": S, "start": DT, "end": DT, "location": S, "notes": S}, ["title", "start"])},
    {"name": "list_events", "description": "List calendar events in a date range (default: next 7 days).",
     "input_schema": _obj({"start_date": D, "end_date": D})},
    {"name": "update_event", "description": "Change or move an event. Moving the start keeps its duration unless end is given.",
     "input_schema": _obj({"event_id": I, "title": S, "start": DT, "end": DT, "location": S, "notes": S}, ["event_id"])},
    {"name": "delete_event", "description": "Delete an event.", "input_schema": _obj({"event_id": I}, ["event_id"])},
    {"name": "find_free_time", "description": "Find free slots within working hours on a day.",
     "input_schema": _obj({"date": D, "duration_minutes": I})},
    {"name": "get_day_overview", "description": "Events, tasks, free time, preferences and last check-in for a day. Use before building a schedule.",
     "input_schema": _obj({"date": D})},
    {"name": "get_today_affirmation", "description": "Today's affirmation.", "input_schema": _obj({})},
    {"name": "rate_affirmation", "description": "Record the user's 1-5 rating of an affirmation.",
     "input_schema": _obj({"affirmation_id": I, "rating": I}, ["affirmation_id", "rating"])},
]

TOOL_FUNCTIONS = {f.__name__: f for f in [
    get_current_time, remember, search_memory, forget, set_preference, get_preferences, log_checkin,
    complete_onboarding, add_task, list_tasks, complete_task, add_event, list_events, update_event,
    delete_event, find_free_time, get_day_overview, get_today_affirmation, rate_affirmation]}

assert set(TOOL_FUNCTIONS) == {t["name"] for t in TOOL_SCHEMAS}


def run_tool(session: Session, name: str, args: dict) -> str:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    try:
        return fn(session, **(args or {}))
    except Exception as e:  # report errors back to the model instead of crashing
        session.rollback()
        return f"Tool error: {e}"
