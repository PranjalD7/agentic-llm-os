import json
import logging
import re
from typing import Dict, List, Optional

import httpx
from pydantic import ValidationError

from ..schemas.planner import PlannerResponse, StepSpec

logger = logging.getLogger("llmos.planner.llm")

# ── Batch planning (legacy, kept for backward compat) ─────────────────────────

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

# ── Iterative planning ─────────────────────────────────────────────────────────

ITERATIVE_SYSTEM_PROMPT = """\
You are a step-by-step shell automation agent for macOS.
You execute one shell command at a time and see the real output before deciding what to do next.

This is a conversation. Each turn you will be shown the result of the last command you ran,
then asked what to do next. You must return JSON deciding the next step.

Response format — always return valid JSON with these exact fields:
  done        (boolean) — true if the task is fully complete, false to continue
  order       (integer) — the step number (1-based); set to 0 when done=true
  description (string)  — what this step does in plain English; set to "" when done=true
  command     (string)  — the exact shell command to run; set to "" when done=true

Critical rules:
- You MUST run at least one shell command before returning done=true
- NEVER return done=true on your first response — always run a command first
- Only return done=true AFTER you have actually executed all necessary commands and seen their output
- Do NOT repeat a command you already ran — check the conversation history
- Use python3, not python. Use python3 -m pip, not bare pip
- Use commands compatible with macOS zsh/bash
- Prefer built-in macOS tools: top -l, vm_stat, sysctl, ps, df, du, ifconfig, date
- Never use Linux-only tools: free, mpstat, apt, systemctl, service
- Homebrew (brew) is already installed — use it directly, never install it
- For brew installs: HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INTERACTIVE=1 brew install <pkg>
- Never use curl | bash, wget | bash patterns
- Never run commands that require a TTY or interactive prompts (no sudo, no passwd, no read)
- Never open GUI applications

"""

ITERATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "done":        {"type": "boolean"},
        "order":       {"type": "integer"},
        "description": {"type": "string"},
        "command":     {"type": "string"},
    },
    "required": ["done", "order", "description", "command"],
}

FIX_SYSTEM_PROMPT = """\
You are a shell command debugger for macOS.
A shell command has failed. Your job is to return a corrected version.

Response format — always return valid JSON with these exact fields:
  done        (boolean) — always false
  order       (integer) — same step number as the failed command
  description (string)  — brief description of the fix
  command     (string)  — the corrected shell command

Rules:
- Fix only the specific error shown — do not rewrite unrelated logic
- Use macOS-compatible commands (zsh/bash)
- Never use interactive flags that require a TTY
- Output ONLY valid JSON — no explanation, no markdown

"""



def _strip_think(raw: str) -> str:
    """Strip <think>...</think> blocks emitted by reasoning models like DeepSeek R1."""
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


class LLMPlanner:
    """
    Planner that calls a local Ollama instance.

    Two modes:
      - plan()      — legacy batch planning (all steps at once)
      - plan_next() — iterative: returns the next single step given history
      - fix_step()  — repair: returns a corrected command after a failure
    """

    def __init__(self, host: str, model: str, max_retries: int):
        self.host = host.rstrip("/")
        self.model = model
        self.max_retries = max_retries

    # ── Iterative API ──────────────────────────────────────────────────────────

    def plan_next(
        self,
        intent: str,
        history: List[Dict],
        workspace_context: Optional[Dict] = None,
    ) -> PlannerResponse:
        """
        Return the next step to execute, or PlannerResponse(done=True) when finished.

        Builds a proper multi-turn conversation so the model sees its own previous
        responses and each step's real output — preventing repeated commands.

        history items: {order, description, command, stdout, stderr, exit_code}
        workspace_context: {files: [...], platform: str, shell: str}
        """
        workspace_files = (workspace_context or {}).get("files", [])
        workspace_str = ", ".join(workspace_files) if workspace_files else "(empty)"

        # First user message always describes the task
        messages = [
            {"role": "system", "content": ITERATIVE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Task: {intent}\n"
                    f"Workspace files: {workspace_str}\n\n"
                    "What is step 1? You MUST run a shell command — never return done=true here."
                ),
            },
        ]

        # Reconstruct the conversation from history so the model sees what it
        # previously returned AND what each command produced.
        for i, h in enumerate(history):
            # What the model said last time (its own assistant turn)
            messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "done": False,
                    "order": h["order"],
                    "description": h["description"],
                    "command": h["command"],
                }),
            })

            # The real result we got back
            result_lines = [f"Step {h['order']} completed (exit_code={h['exit_code']})."]
            if h.get("stdout"):
                result_lines.append(f"Output:\n{h['stdout'][:500]}")
            if h.get("stderr") and h["exit_code"] != 0:
                result_lines.append(f"Error:\n{h['stderr'][:300]}")

            is_last = (i == len(history) - 1)
            if is_last:
                result_lines.append(
                    "\nWhat is the next step? "
                    "Return done=true if the task is now fully complete."
                )
            else:
                result_lines.append(f"\nContinuing to step {h['order'] + 1}.")

            messages.append({"role": "user", "content": "\n".join(result_lines)})

        raw = ""
        for attempt in range(self.max_retries):
            try:
                raw = self._call_ollama(messages, ITERATIVE_SCHEMA)
                logger.debug(f"plan_next raw response: {raw}")
                return self._parse_response(raw)

            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                raise RuntimeError(f"Ollama unavailable: {type(e).__name__}: {e}") from e

            except (json.JSONDecodeError, ValidationError, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"plan_next failed after {self.max_retries} attempt(s): "
                        f"{type(e).__name__}: {e}"
                    ) from e

                logger.debug(f"plan_next attempt {attempt + 1} failed ({e}), retrying")
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Invalid output. Error: {type(e).__name__}: {e}\n"
                        f"Expected JSON with fields: done (bool), order (int), "
                        f"description (str), command (str).\n"
                        f'Example: {{"done": false, "order": 1, '
                        f'"description": "List files", "command": "ls -la"}}\n'
                        f"Output ONLY valid JSON."
                    ),
                })

        raise RuntimeError(f"plan_next exhausted {self.max_retries} retries")

    def fix_step(
        self,
        intent: str,
        history: List[Dict],
        failed_command: str,
        stderr: str,
        step_order: int,
    ) -> PlannerResponse:
        """
        Return a corrected command for a step that failed.
        Returns PlannerResponse with done=False and the fixed command.
        """
        history_lines = []
        for h in history:
            history_lines.append(f"Step {h['order']}: $ {h['command']} (exit={h['exit_code']})")
            if h.get("stdout"):
                history_lines.append(f"  output: {h['stdout'][:200]}")

        history_str = "\n".join(history_lines) if history_lines else "No prior steps."

        user_content = (
            f"Original task: {intent}\n\n"
            f"Steps completed so far:\n{history_str}\n\n"
            f"This command (step {step_order}) failed:\n"
            f"  $ {failed_command}\n"
            f"Error output:\n  {stderr[:500]}\n\n"
            f"Return a corrected command as JSON with step order={step_order}."
        )

        messages = [
            {"role": "system", "content": FIX_SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ]

        raw = ""
        for attempt in range(self.max_retries):
            try:
                raw = self._call_ollama(messages, ITERATIVE_SCHEMA)
                logger.debug(f"fix_step raw response: {raw}")
                return self._parse_response(raw)

            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                raise RuntimeError(f"Ollama unavailable: {type(e).__name__}: {e}") from e

            except (json.JSONDecodeError, ValidationError, KeyError) as e:
                if attempt == self.max_retries - 1:
                    raise RuntimeError(
                        f"fix_step failed after {self.max_retries} attempt(s): "
                        f"{type(e).__name__}: {e}"
                    ) from e

                logger.debug(f"fix_step attempt {attempt + 1} failed ({e}), retrying")
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Invalid output. Error: {type(e).__name__}: {e}\n"
                        f"Return JSON: {{\"done\": false, \"order\": {step_order}, "
                        f"\"description\": \"...\", \"command\": \"...\"}}"
                    ),
                })

        raise RuntimeError(f"fix_step exhausted {self.max_retries} retries")

    # ── Legacy batch API ───────────────────────────────────────────────────────

    def plan(self, intent: str) -> List[StepSpec]:
        """
        Legacy: plan all steps at once. Kept for backward compatibility.
        Prefer plan_next() for new code.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": intent},
        ]
        raw = ""
        for attempt in range(self.max_retries):
            try:
                raw = self._call_ollama(messages, STEP_LIST_SCHEMA)
                logger.debug(f"Ollama raw response: {raw}")
                return self._parse_step_list(raw)

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
                        f"Invalid output. Error: {type(e).__name__}: {e}. "
                        f'Expected: {{"steps": [{{"order": 1, "description": "...", "command": "..."}}]}}\n'
                        f"Output ONLY valid JSON."
                    ),
                })

        raise RuntimeError(f"LLMPlanner exhausted {self.max_retries} retries without a valid response")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _call_ollama(self, messages: list, schema: dict) -> str:
        r = httpx.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": schema,
                "options": {"temperature": 0},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _parse_response(self, raw: str) -> PlannerResponse:
        cleaned = _strip_think(raw)
        data = json.loads(cleaned)
        return PlannerResponse(**data)

    def _parse_step_list(self, raw: str) -> List[StepSpec]:
        cleaned = _strip_think(raw)
        data = json.loads(cleaned)
        return [StepSpec(**s) for s in data["steps"]]
