"""Chat with the assistant from the terminal:  python cli.py
Works offline too (falls back to the local model, then to basic commands).
"""
from app import config
from app.assistant import Assistant
from app.db import SessionLocal, init_db
from app.scheduler import morning_job


def main():
    init_db()
    bot, convo_id = Assistant(), None
    morning_job(bot.backends)  # make sure today's affirmation is ready
    print(f"{config.ASSISTANT_NAME} is ready. Type 'exit' to quit, 'new' for a fresh chat.\n")
    with SessionLocal() as s:
        while True:
            try:
                text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in {"exit", "quit"}:
                break
            if text.lower() == "new":
                convo_id = None
                print("(new chat)\n")
                continue
            if not text:
                continue
            out = bot.chat(s, text, convo_id)
            convo_id = out["conversation_id"]
            tag = f"  [{out['mode']}" + (f" · {', '.join(out['tools_used'])}" if out["tools_used"] else "") + "]"
            print(f"{config.ASSISTANT_NAME}: {out['reply']}{tag}\n")


if __name__ == "__main__":
    main()
