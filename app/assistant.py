"""The assistant: builds context, tries Claude -> local model -> offline commands, saves history."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, offline, onboarding
from app.clock import now_local
from app.db import Conversation, Memory, Message, Preference
from app.llm import BackendUnavailable, default_backends


def build_system_prompt(session: Session) -> str:
    recent = session.scalars(select(Memory).order_by(Memory.id.desc()).limit(30)).all()
    memories = "\n".join(f"- #{m.id} [{m.category}] {m.content}" for m in reversed(recent)) or "(none yet)"
    prefs = "\n".join(f"- {p.key}: {p.value}" for p in session.scalars(select(Preference).where(~Preference.key.startswith("_")).order_by(Preference.key))) or "(none yet)"
    profile = onboarding.get_profile(session)
    return f"""You are {config.ASSISTANT_NAME}, a personal assistant for {config.USER_NAME}.
Now: {now_local():%A %d %B %Y, %H:%M} ({config.TIMEZONE}).

What you do:
- Plan schedules: call get_day_overview first, then propose a realistic plan that respects their working
  hours, focus time and planning style. Only add time blocks to the calendar after they agree.
- Manage the built-in calendar with add_event / list_events / update_event / delete_event. Always use
  'YYYY-MM-DD HH:MM' local times. Mention overlaps the tool warns about.
- Encourage: share today's affirmation when it fits, and record their rating with rate_affirmation.
- Learn and adapt: save structured facts with set_preference and anything else with remember.
  When they say how they feel, log_checkin. If something conflicts with a stored preference, ask and update it.
Be warm, concise and practical. Never invent events or tasks that aren't in the tools' results.

Learning period:
{onboarding.guidance(session)}

Profile summary: {profile.summary or "(not written yet)"}

Preferences:
{prefs}

Memories:
{memories}"""


class Assistant:
    def __init__(self, backends: list | None = None, client=None):
        if backends is None:
            if client is not None:  # convenience for tests: a fake Claude client
                from app.llm import ClaudeBackend
                backends = [ClaudeBackend(client=client)]
            else:
                backends = default_backends()
        self.backends = backends
        self.last_mode = None

    def chat(self, session: Session, user_text: str, conversation_id: int | None = None) -> dict:
        convo = session.get(Conversation, conversation_id) if conversation_id else None
        if convo is None:
            convo = Conversation(title=user_text[:60])
            session.add(convo)
            session.commit()

        history = session.scalars(
            select(Message).where(Message.conversation_id == convo.id)
            .order_by(Message.id.desc()).limit(config.HISTORY_LIMIT)).all()
        messages = [{"role": m.role, "content": m.content} for m in reversed(history)]
        while messages and messages[0]["role"] != "user":  # API needs a user message first
            messages.pop(0)
        messages.append({"role": "user", "content": user_text})

        system = build_system_prompt(session)
        reply, used, mode = None, [], "offline"
        for backend in self.backends:
            try:
                reply, used = backend.run(session, system, messages)
                mode = backend.name
                break
            except BackendUnavailable:
                continue
        if reply is None:
            reply, used = offline.handle(session, user_text)
        self.last_mode = mode

        session.add_all([
            Message(conversation_id=convo.id, role="user", content=user_text),
            Message(conversation_id=convo.id, role="assistant", content=reply or "(no reply)"),
        ])
        session.commit()
        return {"conversation_id": convo.id, "reply": reply, "tools_used": used, "mode": mode}
