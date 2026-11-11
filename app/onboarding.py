"""The 10-day learning period.

No model is retrained. Instead, for the first ONBOARDING_DAYS days the assistant
follows a guided script: it interviews you, checks in daily, saves what it learns
as preferences/memories, and on the last day confirms a profile summary with you.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import today_local
from app.config import ONBOARDING_DAYS, USER_NAME
from app.db import Preference, Profile

# The structured things it tries to learn. Keys are saved with `set_preference`.
CORE_PREFERENCES = {
    "goals": "main goals for the next few months",
    "wake_time": "usual wake-up time (HH:MM)",
    "sleep_time": "usual bedtime (HH:MM)",
    "work_start": "start of working hours (HH:MM)",
    "work_end": "end of working hours (HH:MM)",
    "work_days": "which days are work days (e.g. Mon-Fri)",
    "focus_time": "when they focus best (morning / afternoon / evening)",
    "planning_style": "how they like a day planned (time-blocked, flexible list, top 3)",
    "affirmation_tone": "tone of encouragement that works (gentle, energetic, faith-based, practical…)",
    "affirmation_focus": "what affirmations should support (confidence, calm, discipline…)",
    "stressors": "what tends to stress them out",
    "recharge": "what helps them recharge",
}


def get_profile(session: Session) -> Profile:
    p = session.get(Profile, 1)
    if p is None:
        p = Profile(id=1, onboarding_started=today_local())
        session.add(p)
        session.commit()
    return p


def onboarding_day(session: Session) -> int:
    p = get_profile(session)
    return (today_local() - p.onboarding_started).days + 1


def missing_preferences(session: Session) -> list[str]:
    have = set(session.scalars(select(Preference.key)).all())
    return [k for k in CORE_PREFERENCES if k not in have]


def status(session: Session) -> dict:
    p = get_profile(session)
    day = onboarding_day(session)
    learned = len(CORE_PREFERENCES) - len(missing_preferences(session))
    return {"day": min(day, ONBOARDING_DAYS), "total_days": ONBOARDING_DAYS,
            "completed": p.onboarding_completed, "learned": learned,
            "to_learn": len(CORE_PREFERENCES), "summary": p.summary}


def guidance(session: Session) -> str:
    """Instructions injected into the system prompt for today's phase."""
    p = get_profile(session)
    if p.onboarding_completed:
        return (f"Learning period is complete. Keep adapting: when {USER_NAME} shares how they're doing, "
                "log a check-in; when they reveal a new preference or a changed routine, update it with "
                "set_preference. Use their profile to plan and encourage.")

    day = onboarding_day(session)
    missing = missing_preferences(session)
    gaps = "\n".join(f"  - {k}: {CORE_PREFERENCES[k]}" for k in missing) or "  (all core preferences known)"

    if day == 1:
        phase = (f"This is DAY 1 of a {ONBOARDING_DAYS}-day learning period. Warmly introduce yourself and explain "
                 f"that over the next {ONBOARDING_DAYS} days you'll learn {USER_NAME}'s routine, goals and what "
                 "encouragement works for them, so you can plan their days and write affirmations that fit. "
                 "Ask 2-3 questions at a time, never a long list. Save every answer immediately with "
                 "set_preference (structured) or remember (anything else).")
    elif day < ONBOARDING_DAYS:
        phase = (f"This is DAY {day} of {ONBOARDING_DAYS} of the learning period. In your first reply of the day, "
                 "ask for a quick check-in (mood 1-5, energy 1-5) and log it with log_checkin. Ask whether "
                 "today's affirmation and plan felt right, and adjust preferences from their feedback. "
                 "Then ask 1-2 questions to fill the gaps below. Keep it light; don't interrogate.")
    else:
        phase = (f"The {ONBOARDING_DAYS}-day learning period is ending. Summarise everything you've learned about "
                 f"{USER_NAME} (routine, goals, planning style, encouragement style, what to avoid) in a short, "
                 "friendly profile. Ask them to confirm or correct it. Once they confirm, call "
                 "complete_onboarding with the final summary.")
    return f"{phase}\nStill unknown:\n{gaps}"
