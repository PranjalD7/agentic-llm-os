import datetime
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_BYTES = 1_048_576  # 1 MB

# Injected into every subprocess to prevent package managers from hanging
# on interactive prompts. These are additive — the rest of os.environ is inherited.
_NON_INTERACTIVE_ENV = {
    "HOMEBREW_NO_INTERACTIVE": "1",
    "HOMEBREW_NO_AUTO_UPDATE": "1",
    "HOMEBREW_NO_ANALYTICS": "1",
    "DEBIAN_FRONTEND": "noninteractive",
    "PIP_NO_INPUT": "1",
}


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    started_at: datetime.datetime
    finished_at: datetime.datetime


class Executor:
    """
    Runs shell commands inside the workspace directory.
    Has zero knowledge of policy or risk levels — that's upstream.
    """

    def __init__(self, workspace_dir: Path, timeout_seconds: int = 60):
        self.workspace_dir = workspace_dir
        self.timeout_seconds = timeout_seconds
        workspace_dir.mkdir(parents=True, exist_ok=True)

    def run(self, command: str) -> ExecutionResult:
        started_at = datetime.datetime.utcnow()
        timed_out = False

        env = {**os.environ, **_NON_INTERACTIVE_ENV}

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace_dir,
                capture_output=True,
                timeout=self.timeout_seconds,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            stdout = proc.stdout[:MAX_OUTPUT_BYTES]
            stderr = proc.stderr[:MAX_OUTPUT_BYTES]
            exit_code = proc.returncode

        except subprocess.TimeoutExpired as e:
            raw_stdout = e.stdout or b""
            if isinstance(raw_stdout, bytes):
                raw_stdout = raw_stdout.decode("utf-8", errors="replace")
            stdout = raw_stdout[:MAX_OUTPUT_BYTES]
            stderr = f"[TIMEOUT after {self.timeout_seconds}s]"
            exit_code = -1
            timed_out = True

        except Exception as e:
            stdout = ""
            stderr = f"[EXECUTOR ERROR] {type(e).__name__}: {e}"
            exit_code = -2
            timed_out = False

        finished_at = datetime.datetime.utcnow()
        return ExecutionResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            started_at=started_at,
            finished_at=finished_at,
        )
