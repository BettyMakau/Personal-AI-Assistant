"""Offline tests — a fake Claude client drives the tool loop, no API key or internet needed.
Run:  pytest -q
"""
import os
from datetime import timedelta
from types import SimpleNamespace as NS

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["USE_OLLAMA"] = "false"

import pytest  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app import db  # noqa: E402

# One shared in-memory database for the whole test run.
db.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
db.SessionLocal.configure(bind=db.engine)

from app import affirmations, offline, onboarding, tools  # noqa: E402
from app.assistant import Assistant  # noqa: E402
from app.clock import today_local  # noqa: E402
from app.db import Affirmation, Event, Memory, Profile, Task  # noqa: E402
from app.llm import BackendUnavailable  # noqa: E402


class Block(NS):
    def model_dump(self):
        return dict(vars(self))


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


def tool_use(name, args, id_="t1"):
    return NS(stop_reason="tool_use", content=[Block(type="tool_use", id=id_, name=name, input=args)])


def text(t):
    return NS(stop_reason="end_turn", content=[Block(type="text", text=t)])


@pytest.fixture()
def s():
    db.Base.metadata.drop_all(db.engine)
    db.Base.metadata.create_all(db.engine)
    with db.SessionLocal() as session:
        yield session


def test_chat_saves_memory_and_task(s):
    fake = FakeClient([
        tool_use("remember", {"content": "Betty likes tea", "category": "preference"}),
        tool_use("add_task", {"title": "Call the venue", "due": "2026-11-12"}, "t2"),
        text("Noted, and I've added the task."),
    ])
    out = Assistant(client=fake).chat(s, "I like tea. Remind me to call the venue on the 12th.")
    assert out["mode"] == "claude" and out["tools_used"] == ["remember", "add_task"]
    assert s.query(Memory).one().content == "Betty likes tea"
    assert s.query(Task).one().due == "2026-11-12"

    fake.script.append(text("You like tea."))
    Assistant(client=fake).chat(s, "What do I like?", out["conversation_id"])
    last = fake.calls[-1]
    assert "Betty likes tea" in last["system"]
    assert [m["role"] for m in last["messages"]] == ["user", "assistant", "user"]


def test_calendar_overlap_move_and_free_time(s):
    d = (today_local() + timedelta(days=1)).isoformat()
    tools.set_preference(s, "work_start", "09:00")
    tools.set_preference(s, "work_end", "13:00")
    tools.add_event(s, "Standup", f"{d} 09:00", f"{d} 09:30")
    msg = tools.add_event(s, "Client call", f"{d} 09:15")
    assert "overlaps" in msg
    call = s.query(Event).filter_by(title="Client call").one()
    tools.update_event(s, call.id, start=f"{d} 11:00")          # move keeps 1h duration
    assert call.end.hour == 12
    free = tools.find_free_time(s, d, 60)
    assert "09:30–11:00" in free and "12:00–13:00" in free
    assert "Standup" in tools.list_events(s, d, d)


def test_onboarding_phases(s):
    assert "DAY 1" in onboarding.guidance(s)
    p = s.get(Profile, 1)
    p.onboarding_started = today_local() - timedelta(days=4)
    s.commit()
    assert "DAY 5 of 10" in onboarding.guidance(s)
    p.onboarding_started = today_local() - timedelta(days=9)
    s.commit()
    assert "complete_onboarding" in onboarding.guidance(s)
    tools.complete_onboarding(s, "Early riser who likes gentle encouragement.")
    assert onboarding.status(s)["completed"] is True
    tools.set_preference(s, "wake_time", "05:30")
    assert onboarding.status(s)["learned"] == 1


class FakeWriter:
    name = "claude"

    def complete(self, prompt):
        import re
        self.prompt = prompt
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", prompt.split("\n")[0])
        return "[" + ",".join(f'{{"date":"{d}","theme":"calm","text":"Fresh {d}"}}' for d in dates) + "]"


def test_affirmations_adapt_and_bank(s):
    builtin = affirmations.get_for_date(s, today_local())
    assert builtin.source == "builtin"
    tools.rate_affirmation(s, builtin.id, 5)
    tools.set_preference(s, "affirmation_tone", "faith-based")
    w = FakeWriter()
    n = affirmations.refresh(s, w)
    assert n == 6                                   # rated today kept; 6 future days banked
    assert "faith-based" in w.prompt and builtin.text in w.prompt   # uses tone + liked ones
    assert affirmations.get_for_date(s, today_local()).id == builtin.id


def test_falls_back_to_offline_commands(s):
    class Down:
        name = "claude"

        def run(self, *a):
            raise BackendUnavailable("no internet")

    bot = Assistant(backends=[Down()])
    out = bot.chat(s, "add task Buy airtime")
    assert out["mode"] == "offline" and "Added task" in out["reply"]
    d = today_local().isoformat()
    assert "Added event" in offline.handle(s, f"add event Dentist {d} 14:00")[0]
    assert "Dentist" in bot.chat(s, "what's my schedule today")["reply"]
    assert "offline" in bot.chat(s, "write me a poem")["reply"]
