"""Daily affirmations that adapt to you.

- Each morning (when online) today's affirmation is written fresh from your goals,
  preferred tone, recent check-ins and the ratings you've given past affirmations.
- A bank of the next few days is generated ahead of time so you still get one offline.
- If nothing was generated, a built-in affirmation is used.
"""
import json
import re
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import today_local
from app.config import AFFIRMATION_BANK_DAYS, USER_NAME
from app.db import Affirmation, CheckIn, Preference

BUILTIN = [
    ("confidence", "I bring real skill and care to everything I do today."),
    ("calm", "I can take this one step at a time. I don't have to do it all at once."),
    ("growth", "Every problem I work through makes me sharper."),
    ("discipline", "Small, steady actions today build the life I want."),
    ("self-worth", "My worth isn't measured by my to-do list."),
    ("focus", "I give my full attention to what matters most right now."),
    ("resilience", "I've handled hard days before, and I can handle this one."),
    ("gratitude", "There is something good in today, and I will notice it."),
    ("rest", "Resting is part of the work, not a break from it."),
    ("courage", "I can feel unsure and still take the next step."),
    ("progress", "Progress counts, even when it's quiet."),
    ("boundaries", "Saying no to some things lets me say yes to what matters."),
    ("joy", "I make room for something that makes me smile today."),
    ("purpose", "My work and my goals are worth showing up for."),
]


def builtin_for(d: date) -> tuple[str, str]:
    return BUILTIN[d.toordinal() % len(BUILTIN)]


def get_for_date(session: Session, d: date) -> Affirmation:
    """Return the affirmation for a date, creating a built-in one if none exists."""
    a = session.scalars(select(Affirmation).where(Affirmation.for_date == d)
                        .order_by(Affirmation.id.desc())).first()
    if a is None:
        theme, text = builtin_for(d)
        a = Affirmation(for_date=d, text=text, theme=theme, source="builtin")
        session.add(a)
        session.commit()
    return a


def _context(session: Session) -> str:
    prefs = {p.key: p.value for p in session.scalars(select(Preference)).all()}
    checkins = session.scalars(select(CheckIn).order_by(CheckIn.id.desc()).limit(7)).all()
    rated = session.scalars(select(Affirmation).where(Affirmation.rating.is_not(None))
                            .order_by(Affirmation.id.desc()).limit(20)).all()
    liked = [a.text for a in rated if a.rating >= 4][:5]
    disliked = [a.text for a in rated if a.rating <= 2][:5]
    ci = [f"{c.day}: mood {c.mood}/5, energy {c.energy or '?'}/5, {c.note or ''}" for c in checkins]
    return (f"Goals: {prefs.get('goals', 'unknown')}\n"
            f"Preferred tone: {prefs.get('affirmation_tone', 'warm and practical')}\n"
            f"Should support: {prefs.get('affirmation_focus', 'confidence and calm')}\n"
            f"Stressors: {prefs.get('stressors', 'unknown')}\n"
            f"Recent check-ins:\n" + ("\n".join(ci) or "none") + "\n"
            f"Affirmations they liked: {liked or 'none yet'}\n"
            f"Affirmations they disliked: {disliked or 'none yet'}")


def _parse(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [i for i in items if isinstance(i, dict) and i.get("text")]


def generate(session: Session, backend, dates: list[date], replace: bool = False) -> int:
    """Ask a backend to write affirmations for the given dates. Returns how many were saved."""
    if not dates:
        return 0
    prompt = (f"Write {len(dates)} daily affirmations for {USER_NAME}, one per date: "
              f"{', '.join(d.isoformat() for d in dates)}.\n"
              "Make each one first person, one or two sentences, specific to what you know, and varied. "
              "Lean toward the styles they liked and away from those they disliked. If recent check-ins show "
              "low mood or energy, be gentler and more supportive.\n\n"
              f"What we know:\n{_context(session)}\n\n"
              'Reply with ONLY a JSON array: [{"date": "YYYY-MM-DD", "theme": "one word", "text": "..."}]')
    items = _parse(backend.complete(prompt))
    saved = 0
    for d, item in zip(dates, items):
        existing = session.scalars(select(Affirmation).where(Affirmation.for_date == d)).all()
        if existing and not replace:
            continue
        for a in existing:
            if a.rating is None:  # never discard one you've already rated
                session.delete(a)
        session.add(Affirmation(for_date=d, text=item["text"].strip(), theme=item.get("theme"), source=backend.name))
        saved += 1
    session.commit()
    return saved


def refresh(session: Session, backend) -> int:
    """Morning job: rewrite today's (if not yet rated) and top up the offline bank."""
    today = today_local()
    saved = 0
    todays = session.scalars(select(Affirmation).where(Affirmation.for_date == today)).all()
    if not any(a.rating is not None for a in todays):
        # Rewrite today's using the latest check-ins (the banked one may be days old).
        saved += generate(session, backend, [today], replace=True)
    future = [today + timedelta(days=i) for i in range(1, AFFIRMATION_BANK_DAYS)]
    have = set(session.scalars(select(Affirmation.for_date).where(Affirmation.for_date.in_(future))).all())
    saved += generate(session, backend, [d for d in future if d not in have])
    return saved
