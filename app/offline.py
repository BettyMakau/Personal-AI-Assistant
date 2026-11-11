"""Offline commands: used when neither Claude nor a local model is reachable.

Understands simple phrases so the essentials keep working without internet.
"""
import re

from sqlalchemy.orm import Session

from app.clock import today_local
from app import tools

HELP = ("I'm offline right now, so I can only do the basics. Try:\n"
        "• today — your day at a glance\n"
        "• affirmation\n"
        "• tasks  /  add task Call the venue  /  done 3\n"
        "• events  /  add event Dentist 2026-11-12 14:00\n"
        "• mood 4 — log a check-in (1-5)")


def handle(session: Session, text: str) -> tuple[str, list[str]]:
    t = text.strip()
    low = t.lower()

    if m := re.match(r"^add task (.+)$", t, re.I):
        return tools.add_task(session, m.group(1).strip()), ["add_task"]
    if m := re.match(r"^(?:done|complete) #?(\d+)$", low):
        return tools.complete_task(session, int(m.group(1))), ["complete_task"]
    if m := re.match(r"^add event (.+?) (\d{4}-\d{2}-\d{2})(?:[ t](\d{1,2}:\d{2}))?$", t, re.I):
        start = f"{m.group(2)} {m.group(3) or '09:00'}"
        return tools.add_event(session, m.group(1).strip(), start), ["add_event"]
    if m := re.match(r"^mood (\d)(?: energy (\d))?(?: (.*))?$", low):
        return tools.log_checkin(session, int(m.group(1)), int(m.group(2)) if m.group(2) else None, m.group(3)), ["log_checkin"]
    if "affirmation" in low:
        return tools.get_today_affirmation(session), ["get_today_affirmation"]
    if any(w in low for w in ("today", "agenda", "schedule", "my day")):
        return tools.get_day_overview(session, today_local().isoformat()), ["get_day_overview"]
    if "task" in low or "to do" in low or "todo" in low:
        return tools.list_tasks(session), ["list_tasks"]
    if any(w in low for w in ("event", "calendar", "week")):
        return tools.list_events(session), ["list_events"]
    return HELP, []
