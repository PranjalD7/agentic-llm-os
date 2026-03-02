import json
import logging
import re
from typing import List

import httpx
from pydantic import ValidationError

from ..schemas.planner import StepSpec

logger = logging.getLogger("llmos.planner.llm")

SYSTEM_PROMPT = """\
You are a task planning assistant for a supervised macOS automation system.
Given a natural-language intent, return a single JSON object containing
an ordered list of shell commands that accomplish the intent completely.

Rules:
- Output ONLY the JSON object — no explanation, no markdown, no commentary
- Use python3, not python. Use python3 -m pip, not bare pip
- Use commands compatible with macOS zsh/bash
- Prefer built-in macOS tools: top -l, vm_stat, sysctl, ps, df, du, ifconfig, networksetup, osascript
- Never use Linux-only tools: free, mpstat, apt, systemctl, service
- Homebrew (brew) is already installed — never install it, never use its install script
- For brew installs, always prefix with environment flags to avoid any prompts:
  HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INTERACTIVE=1 brew install <pkg>
- Never use curl | bash, wget | bash, or $( curl ... ) patterns
- Never run commands that require a TTY or interactive prompts (no sudo, no passwd, no read)
- Never open GUI applications or use open/osascript to launch apps

"""

# Passed as the `format` field to Ollama — constrains model output to this exact shape.
STEP_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order":       {"type": "integer"},
                    "description": {"type": "string"},
                    "command":     {"type": "string"},
                },
                "required": ["order", "description", "command"],
            },
        }
    },
    "required": ["steps"],
}


class LLMPlanner:
    """
    Planner that calls a local Ollama instance to convert natural language
    into an ordered list of StepSpec objects.

    Interface: plan(intent: str) -> List[StepSpec]

    Raises RuntimeError when:
    - Ollama is unreachable (ConnectError, Timeout)
    - Response fails JSON/schema validation after max_retries
    """

    def __init__(self, host: str, model: str, max_retries: int):
        self.host = host.rstrip("/")
        self.model = model
        self.max_retries = max_retries

    def plan(self, intent: str) -> List[StepSpec]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": intent},
        ]
        raw = ""
        for attempt in range(self.max_retries):
            try:
                raw = self._call_ollama(messages)
                logger.debug(f"Ollama raw response: {raw}")
                return self._parse(raw)

            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                raise RuntimeError(f"Ollama unavailable: {type(e).__name__}: {e}") from e

            except (json.JSONDecodeError, ValidationError, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"LLMPlanner failed after {self.max_retries} attempt(s): "
                        f"{type(e).__name__}: {e}"
                    ) from e

                logger.debug(f"Attempt {attempt + 1} failed ({e}), retrying with correction")
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Invalid output. Error: {e}. "
                        f"Retry using the exact JSON schema provided."
                    ),
                })

        raise RuntimeError(f"LLMPlanner exhausted {self.max_retries} retries without a valid response")

    def _call_ollama(self, messages: list) -> str:
        r = httpx.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": STEP_LIST_SCHEMA,
                "options": {"temperature": 0},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _parse(self, raw: str) -> List[StepSpec]:
        # Strip <think>...</think> blocks emitted by DeepSeek R1 and similar models
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        data = json.loads(cleaned)
        return [StepSpec(**s) for s in data["steps"]]
