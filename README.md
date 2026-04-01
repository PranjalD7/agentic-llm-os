# ShellMind

A local, privacy-first task automation system that converts natural language into shell commands, executes them safely, and keeps a human in the loop for any risky operations. Ships as a native macOS desktop app.

```
nlsh run "find all large files in my home directory and show a summary"
```

---

## How It Works

1. **You describe a task in plain English** — e.g. `"compress all logs older than 30 days"`
2. **The Iterative LLM Planner** (powered by a local [Ollama](https://ollama.com) model) decides one step at a time, seeing the real output of each command before planning the next
3. **The Policy Engine** classifies each command as `SAFE`, `RISKY`, or `BLOCKED`
4. **SAFE** commands execute automatically
5. **RISKY** commands pause and ask you to approve or reject before running
6. **BLOCKED** commands are refused outright
7. If a command fails, the planner automatically attempts to fix and retry it (up to `STEP_RETRY_LIMIT` times)
8. A full audit trail of every task and step is stored in SQLite

```
┌──────────────────┐    HTTP     ┌────────────────────────────────────────────┐
│  ShellMind       │ ──────────▶ │              llmos-daemon (FastAPI)        │
│  Desktop App     │             │  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  (Tauri + React) │ ◀────────── │  │ LLM      │  │ Policy   │  │ Executor │ │
└──────────────────┘             │  │ Planner  │  │ Engine   │  │ Runner   │ │
                                 │  └──────────┘  └──────────┘  └──────────┘ │
┌─────────────┐                  │              Worker Thread                 │
│  nlsh CLI   │ ──────────────▶  │                                            │
│  (Typer)    │ ◀────────────── │              SQLite (audit log)            │
└─────────────┘                  └────────────────────────────────────────────┘
```

---

## Features

- **Native macOS desktop app** — lives in the menu bar, toggle with `Cmd+Shift+Space` or the tray icon
- **Natural language → shell commands** via a local Ollama LLM (no data sent to the cloud)
- **Iterative planning** — the LLM sees real command output before deciding the next step, not a fixed upfront plan
- **Self-healing steps** — failed commands are automatically sent back to the LLM for a fix and retried
- **Three-tier policy engine**: SAFE / RISKY / BLOCKED with configurable regex rules
- **Human-in-the-loop approval** for risky operations — approve or reject interactively
- **Full audit trail** in SQLite — every task, step, command, stdout, stderr, and exit code
- **REST API** — everything is accessible via HTTP (see [API Reference](#api-reference))
- **macOS-optimised** — LLM is prompted to use native macOS tools (`top -l`, `vm_stat`, `sysctl`, etc.)

---

## Architecture

```
src/llmos/
├── api/
│   ├── app.py            # FastAPI app + lifespan (DB init, worker start)
│   └── routes/
│       ├── tasks.py      # POST /tasks, GET /tasks, GET /tasks/{id}
│       └── approvals.py  # POST /tasks/{id}/approve|reject|cancel
├── cli/
│   ├── main.py           # nlsh CLI commands (run, status, list, approve, reject, cancel)
│   └── client.py         # httpx wrapper around the daemon REST API
├── config.py             # Pydantic Settings — env vars with defaults
├── db/
│   ├── engine.py         # SQLAlchemy engine + session factory
│   └── models.py         # Task and Step ORM models
├── executor/
│   └── runner.py         # subprocess runner (captures stdout/stderr)
├── planner/
│   └── llm.py            # LLMPlanner — iterative plan_next/fix_step via Ollama
├── policy/
│   ├── engine.py         # PolicyEngine — evaluates commands against rules
│   └── rules.py          # BLOCKED_PATTERNS and RISKY_PATTERNS (regex + reason)
├── schemas/
│   ├── enums.py          # TaskState, StepState, RiskLevel enums
│   ├── planner.py        # PlannerResponse schema
│   └── task.py           # Pydantic request/response schemas
└── worker/
    └── loop.py           # Background thread: iterative plan→policy→execute loop with retries

gui/
├── src/                  # React frontend (Vite)
└── src-tauri/            # Tauri desktop shell (Rust)
    ├── src/
    │   ├── main.rs       # App lifecycle, tray icon, global shortcut, daemon management
    │   └── voice.rs      # macOS NSSpeechRecognizer wake word + Whisper transcription
    └── tauri.conf.json
```

### Task State Machine

```
PENDING → PLANNING → RUNNING → (loop: plan_next → policy → execute)
                                    ↘ AWAITING_APPROVAL → (approved) → back to RUNNING
                                                       → (rejected) → CANCELLED
                                    ↘ step failed → fix_step retry → back to RUNNING
                                    ↘ planner returns done=true → SUCCESS
                                    ↘ unrecoverable error → FAILED
```

---

## Requirements

- Python ≥ 3.9
- [Ollama](https://ollama.com) running locally with a compatible model pulled
- macOS (designed and tested on macOS)
- Node.js ≥ 18
- Rust + [Tauri CLI](https://tauri.app) *(for building the desktop app)*

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/PranjalD7/agentic-llm-os.git
cd agentic-llm-os
```

### 2. Set up the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env to match your setup
```

Key variables:

| Variable | Default | Description |
|---|---|---|
| `DAEMON_HOST` | `127.0.0.1` | Host the daemon binds to |
| `DAEMON_PORT` | `7777` | Port the daemon listens on |
| `DATABASE_URL` | `sqlite:///./llmos.db` | SQLAlchemy database URL |
| `STEP_TIMEOUT_SECONDS` | `3000` | Max seconds per command |
| `APPROVAL_TIMEOUT_SECONDS` | `360000` | Seconds to wait for human approval |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `qwen3-coder:30b` | Model name to use for planning |
| `LLM_MAX_RETRIES` | `3` | Retry attempts on malformed LLM output |
| `MAX_STEPS_PER_TASK` | `20` | Safety cap: max steps the iterative planner can take |
| `STEP_RETRY_LIMIT` | `2` | Times a failed step is sent to the LLM for a fix before giving up |

### 4. Pull an Ollama model

```bash
# Install Ollama from https://ollama.com, then:
ollama pull qwen3-coder:30b

# Or use a smaller model for faster responses:
ollama pull qwen2.5-coder:7b
```

Update `OLLAMA_MODEL` in your `.env` to match.

---

## Usage

### Desktop App

```bash
cd gui
npm install
npx tauri dev
```

The app lives in the menu bar. Use `Cmd+Shift+Space` to toggle the window, or click the tray icon.

The Python daemon starts and stops automatically with the app.

### CLI

```bash
# Start the daemon manually (if not using the desktop app)
llmos-daemon

# Submit a task and watch it run
nlsh run "show me disk usage by directory in my home folder"

# Submit without watching
nlsh run "list running processes sorted by CPU" --no-watch

# List recent tasks
nlsh list

# Check a specific task
nlsh status <task-id>

# Approve a pending risky step
nlsh approve <task-id>

# Reject a pending risky step
nlsh reject <task-id>

# Cancel a running task
nlsh cancel <task-id>
```

### Example session

```
$ nlsh run "check available disk space and memory"

Task created: a1b2c3d4-...
Intent:       check available disk space and memory
  → PLANNING
  → RUNNING

Steps (2):
  [ ] ✓  1. Check available disk space
         $ df -h
         exit=0
         │ Filesystem      Size   Used  Avail Capacity  Mount
         │ /dev/disk3s1s1  460G   112G   180G    39%    /

  [ ] ✓  2. Check memory usage
         $ vm_stat | head -20
         exit=0
         │ Mach Virtual Memory Statistics: (page size of 16384 bytes)
         │ Pages free: 12345.
         ...
```

---

## API Reference

The daemon exposes a REST API at `http://localhost:7777`.

Interactive docs are available at `http://localhost:7777/docs` when the daemon is running.

### Tasks

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/tasks` | Create a new task |
| `GET` | `/tasks` | List all tasks |
| `GET` | `/tasks/{id}` | Get task details and steps |

**Create task** — `POST /tasks`
```json
{ "intent": "show current CPU usage" }
```

**Task response**
```json
{
  "id": "a1b2c3d4-...",
  "intent": "show current CPU usage",
  "state": "SUCCESS",
  "steps": [
    {
      "order": 1,
      "description": "Show CPU usage",
      "command": "top -l 1 | head -20",
      "state": "SUCCESS",
      "risk_level": "SAFE",
      "exit_code": 0,
      "stdout": "...",
      "stderr": "",
      "requires_approval": false,
      "approval_decision": null
    }
  ]
}
```

### Approvals

| Method | Path | Description |
|---|---|---|
| `POST` | `/tasks/{id}/approve` | Approve the pending risky step |
| `POST` | `/tasks/{id}/reject` | Reject the pending risky step |
| `POST` | `/tasks/{id}/cancel` | Cancel a running or pending task |

---

## Policy Engine

Commands are evaluated against two lists of regex patterns in [src/llmos/policy/rules.py](src/llmos/policy/rules.py).

### BLOCKED (always refused)

Examples: disk formatting (`mkfs`, `dd if=`), fork bombs, piping `curl`/`wget` to a shell, netcat listeners, reverse shell patterns, deleting `/etc/passwd`.

### RISKY (require human approval)

Examples: `pip install`, `npm install`, `brew install`, `rm -r`, `curl`, `wget`, `ssh`, `git push`, `sudo`, `chmod`, `kill`.

### SAFE

Everything else — read-only commands, file listing, text processing, most system info queries.

You can extend the policy by editing the `BLOCKED_PATTERNS` and `RISKY_PATTERNS` lists directly.

---

## Running Tests

```bash
source .venv/bin/activate
pytest
```

Test modules:

| File | What it tests |
|---|---|
| `tests/test_policy.py` | Policy engine rule matching |
| `tests/test_executor.py` | Subprocess executor (stdout, stderr, exit codes) |
| `tests/test_api.py` | FastAPI routes via TestClient |
