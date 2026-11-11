"""The two "brains" and how we switch between them.

ClaudeBackend  - online, most capable.
OllamaBackend  - a small model running on your own laptop; works without internet.
If neither is reachable, assistant.py falls back to offline commands (offline.py).
"""
import httpx
from sqlalchemy.orm import Session

from app import config
from app.tools import TOOL_SCHEMAS, run_tool

MAX_TOOL_ROUNDS = 8


class BackendUnavailable(Exception):
    """Raised when a backend can't be reached (no internet, no key, Ollama not running)."""


class ClaudeBackend:
    name = "claude"

    def __init__(self, client=None):
        self._client = client  # can be injected (e.g. a fake in tests)

    @property
    def client(self):
        if self._client is None:
            if not config.ANTHROPIC_API_KEY:
                raise BackendUnavailable("ANTHROPIC_API_KEY not set")
            from anthropic import Anthropic
            self._client = Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=30, max_retries=1)
        return self._client

    def _create(self, **kw):
        try:
            return self.client.messages.create(model=config.CLAUDE_MODEL, max_tokens=config.MAX_TOKENS, **kw)
        except BackendUnavailable:
            raise
        except Exception as e:
            # Connection / timeout errors mean we're offline -> let the next backend try.
            if type(e).__name__ in {"APIConnectionError", "APITimeoutError", "ConnectError"}:
                raise BackendUnavailable(str(e)) from e
            raise

    def run(self, session: Session, system: str, messages: list[dict]) -> tuple[str, list[str]]:
        messages, used = list(messages), []
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self._create(system=system, tools=TOOL_SCHEMAS, messages=messages)
            calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not calls:
                return "\n".join(b.text for b in resp.content if b.type == "text").strip(), used
            messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
            results = []
            for c in calls:
                used.append(c.name)
                results.append({"type": "tool_result", "tool_use_id": c.id, "content": run_tool(session, c.name, c.input)})
            messages.append({"role": "user", "content": results})
        return "Sorry, I got stuck in a loop of tool calls. Could you rephrase?", used

    def complete(self, prompt: str) -> str:
        resp = self._create(messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in resp.content if b.type == "text")


class OllamaBackend:
    """Talks to a local Ollama server (https://ollama.com). Install, then: ollama pull llama3.2"""
    name = "ollama"

    def __init__(self, url: str | None = None, model: str | None = None):
        self.url, self.model = (url or config.OLLAMA_URL).rstrip("/"), model or config.OLLAMA_MODEL

    def _post(self, payload: dict) -> dict:
        if not config.USE_OLLAMA:
            raise BackendUnavailable("Ollama disabled")
        try:
            r = httpx.post(f"{self.url}/api/chat", json={"model": self.model, "stream": False, **payload}, timeout=120)
            r.raise_for_status()
            return r.json()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            raise BackendUnavailable(f"Ollama not reachable: {e}") from e

    def available(self) -> bool:
        if not config.USE_OLLAMA:
            return False
        try:
            return httpx.get(f"{self.url}/api/tags", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _tools():
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in TOOL_SCHEMAS]

    def run(self, session: Session, system: str, messages: list[dict]) -> tuple[str, list[str]]:
        msgs = [{"role": "system", "content": system + "\n(You are running in offline mode on a small local model. Keep replies short.)"}]
        msgs += [m for m in messages if isinstance(m["content"], str)]
        used = []
        for _ in range(MAX_TOOL_ROUNDS):
            msg = self._post({"messages": msgs, "tools": self._tools()}).get("message", {})
            calls = msg.get("tool_calls") or []
            if not calls:
                return (msg.get("content") or "").strip(), used
            msgs.append(msg)
            for c in calls:
                fn = c.get("function", {})
                used.append(fn.get("name", "?"))
                out = run_tool(session, fn.get("name", ""), fn.get("arguments") or {})
                msgs.append({"role": "tool", "content": out, "tool_name": fn.get("name")})
        return "Sorry, I got stuck. Try a simpler request.", used

    def complete(self, prompt: str) -> str:
        return self._post({"messages": [{"role": "user", "content": prompt}]}).get("message", {}).get("content", "")


def default_backends() -> list:
    return [ClaudeBackend(), OllamaBackend()]
