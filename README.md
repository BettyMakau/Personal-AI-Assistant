# Ava — Personal Assistant (v2)

A personal assistant that runs on your own laptop. It plans your days, keeps its own
calendar, writes a daily affirmation that fits how you're doing, spends its first
10 days learning about you, and keeps the basics working when you're offline.

## How it thinks

Each message goes to the first "brain" that's reachable:

1. **Claude** (online). The most capable option, it can do everything.
2. **A local model via Ollama** (offline, optional). Smaller, but it can still use the tools.
3. **Offline commands.** No AI at all. It understands simple phrases like `today`,
   `add task …`, `add event Dentist 2026-11-12 14:00`, `mood 4` and `affirmation`.

Your data (calendar, tasks, memories, check-ins) lives in a local SQLite file, so it's
always available. The badge in the top-right corner shows which brain answered last.

## Features

| Feature | How it works |
|---|---|
| **Built-in calendar** | Add, move and delete events from chat or the Calendar tab. It warns you about overlaps and finds free slots inside your working hours. |
| **Schedules** | "Plan my day" makes it read your events, tasks, free time, routine and last check-in, then propose a plan. It only adds time blocks after you agree. |
| **Daily affirmations** | Every morning (06:00 by default) it writes today's affirmation using your goals, preferred tone, recent check-ins and your ratings of past affirmations. Rate each one from 1 to 5 to steer it. |
| **10-day learning period** | Day 1 is an intro interview. Days 2–9 are short daily check-ins plus one or two questions. Day 10 is a profile summary for you to confirm. Progress shows on the Today and About me tabs. |
| **Memory** | It saves structured *preferences* (wake time, work hours, goals, tone…) and free-form *memories*. You can review them, and forget memories, on the About me tab. |
| **Adapting** | Check-ins, affirmation ratings and corrections update its preferences, and every reply uses the latest ones. |
| **Offline** | The calendar, tasks and check-ins always work. Seven days of affirmations are written in advance whenever it's online, and built-in ones fill any gap. |

The 10-day learning period doesn't retrain the AI. It's a guided routine that fills the
assistant's memory, so after day 10 it knows your routine and style.

## Quick start (Windows, VS Code terminal)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # paste your key into ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and click **Continue today's session** to start day 1.
Terminal instead: `python cli.py`. Tests (no key needed): `pytest -q`.

Check the current model IDs at https://docs.claude.com/en/docs/about-claude/models
and set `CLAUDE_MODEL` in `.env`.

### Optional: offline AI with Ollama

1. Install Ollama from https://ollama.com.
2. Run `ollama pull llama3.2` (about 2 GB; any model that supports tool calling works).
3. Leave Ollama running. When Claude can't be reached, the app switches to it automatically.

## Project layout

```
app/
  main.py          web app + API, starts the morning scheduler
  assistant.py     builds the prompt (profile, preferences, memories, learning phase), picks a brain
  llm.py           Claude and Ollama backends with the tool-calling loop
  tools.py         everything the AI can do: calendar, tasks, memory, preferences, check-ins, affirmations
  onboarding.py    the 10-day learning script and the list of things it tries to learn
  affirmations.py  adaptive generation, the offline bank, built-in fallbacks
  scheduler.py     morning job (today's affirmation + the bank for the coming days)
  offline.py       no-AI command parser
  clock.py         local time helpers (TIMEZONE in .env)
  db.py            tables: conversations, messages, profile, preferences, memories,
                   check-ins, tasks, events, affirmations
  static/index.html  UI: Today · Calendar · Chat · About me
cli.py             terminal chat
tests/             offline tests with a fake Claude
```

## Handy API endpoints

`GET /api/today` · `GET/POST /api/events` · `PATCH/DELETE /api/events/{id}` ·
`POST /api/checkin` · `POST /api/affirmations/{id}/rate` · `POST /api/affirmations/refresh` ·
`POST /api/chat` · `GET /api/me` · `GET /api/status`

Power Automate can call these, for example to send today's affirmation to WhatsApp or email
each morning from `GET /api/today`.

## Ideas for next steps

- Morning push notifications (browser notifications, or WhatsApp like the ticketing project).
- Recurring events (weekly standup, gym days).
- Semantic memory search with pgvector once you move to PostgreSQL.
- A small mood/energy trend chart on the About me tab.
- Turning the UI into an installable app (PWA) for your phone.
