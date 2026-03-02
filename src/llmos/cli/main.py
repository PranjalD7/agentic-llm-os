import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from .client import DaemonClient

app = typer.Typer(name="nlsh", help="Natural Language Shell — Agentic LLM OS", no_args_is_help=True)
console = Console()

TERMINAL_STATES = {"SUCCESS", "FAILED", "CANCELLED"}

STATE_STYLE = {
    "PENDING":           "dim",
    "PLANNING":          "cyan",
    "RUNNING":           "blue",
    "AWAITING_APPROVAL": "yellow bold",
    "SUCCESS":           "green bold",
    "FAILED":            "red bold",
    "CANCELLED":         "dim red",
}

STEP_ICON = {
    "PENDING": "○",
    "RUNNING": "●",
    "SUCCESS": "✓",
    "FAILED":  "✗",
    "SKIPPED": "—",
}

RISK_ICON = {
    "SAFE":    " ",
    "RISKY":   "!",
    "BLOCKED": "✗",
}


def _styled_state(state: str) -> str:
    style = STATE_STYLE.get(state, "")
    return f"[{style}]{state}[/{style}]" if style else state


def _print_task(task: dict):
    console.print(f"\n[bold]Task[/bold]  {task['id']}")
    console.print(f"[bold]State[/bold] {_styled_state(task['state'])}")
    if task.get("error_msg"):
        console.print(f"[bold]Error[/bold] [red]{task['error_msg']}[/red]")

    steps = task.get("steps", [])
    if not steps:
        return

    console.print(f"\n[bold]Steps ({len(steps)}):[/bold]")
    for step in steps:
        risk  = RISK_ICON.get(step["risk_level"], "?")
        icon  = STEP_ICON.get(step["state"], "?")
        style = STATE_STYLE.get(step["state"], "")
        label = f"[{style}]{icon}[/{style}]" if style else icon
        console.print(f"  [{risk}] {label}  {step['order']}. {step['description']}")
        console.print(f"         [dim]$ {step['command']}[/dim]")
        if step.get("exit_code") is not None:
            console.print(f"         exit={step['exit_code']}")
        if step.get("stdout"):
            for line in step["stdout"].splitlines()[:15]:
                console.print(f"         [dim]│ {line}[/dim]")
        if step.get("stderr") and step["state"] == "FAILED":
            for line in step["stderr"].splitlines()[:10]:
                console.print(f"         [red]│ {line}[/red]")


def _handle_approval(client: DaemonClient, task: dict) -> bool:
    """Print approval prompt, get user input. Returns True to keep watching."""
    awaiting = next(
        (s for s in task["steps"]
         if s["requires_approval"] and s["approval_decision"] is None),
        None,
    )
    if awaiting is None:
        time.sleep(0.5)
        return True

    console.print("\n" + "=" * 60)
    console.print("[yellow bold]APPROVAL REQUIRED[/yellow bold]")
    console.print("=" * 60)
    console.print(f"Step {awaiting['order']}: [bold]{awaiting['description']}[/bold]")
    console.print(f"Command: [cyan]$ {awaiting['command']}[/cyan]")
    console.print(f"Reason:  [yellow]{awaiting['approval_reason']}[/yellow]")
    console.print("=" * 60)

    decision = typer.prompt("Approve? [y/n]", default="n").strip().lower()

    if decision in ("y", "yes"):
        client.approve_task(task["id"])
        console.print("[green]Approved. Continuing...[/green]")
    else:
        client.reject_task(task["id"])
        console.print("[red]Rejected. Task cancelled.[/red]")
        return False

    return True


def _watch(client: DaemonClient, task_id: str):
    last_state = None
    while True:
        task = client.get_task(task_id)
        state = task["state"]

        if state != last_state:
            console.print(f"  → {_styled_state(state)}")
            last_state = state

        if state == "AWAITING_APPROVAL":
            keep_going = _handle_approval(client, task)
            last_state = None  # force state print after decision
            if not keep_going:
                _print_task(client.get_task(task_id))
                sys.exit(0)
            continue

        if state in TERMINAL_STATES:
            _print_task(task)
            if state == "FAILED":
                sys.exit(1)
            return

        time.sleep(1)


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command("run")
def run_task(
    intent: str = typer.Argument(..., help="Natural language task description"),
    watch: bool = typer.Option(True, "--watch/--no-watch",
                               help="Poll for completion and show live status"),
):
    """Submit a task and optionally watch it run."""
    client = DaemonClient()
    task = client.create_task(intent)
    console.print(f"[bold]Task created:[/bold] {task['id']}")
    console.print(f"[bold]Intent:[/bold]       {task['intent']}")

    if watch:
        _watch(client, task["id"])
    else:
        console.print(f"[bold]State:[/bold]        {_styled_state(task['state'])}")


@app.command("status")
def task_status(task_id: str = typer.Argument(..., help="Task ID")):
    """Show the current state of a task and its steps."""
    client = DaemonClient()
    task = client.get_task(task_id)
    _print_task(task)


@app.command("list")
def list_tasks():
    """List recent tasks."""
    client = DaemonClient()
    tasks = client.list_tasks()

    if not tasks:
        console.print("[dim]No tasks yet.[/dim]")
        return

    table = Table(box=box.SIMPLE)
    table.add_column("ID",     style="dim", width=10)
    table.add_column("State",  width=20)
    table.add_column("Intent", width=60)
    table.add_column("Steps",  width=6, justify="right")

    for t in tasks:
        short_id = t["id"][:8] + "..."
        state_str = _styled_state(t["state"])
        intent = t["intent"][:57] + "..." if len(t["intent"]) > 57 else t["intent"]
        table.add_row(short_id, state_str, intent, str(len(t.get("steps", []))))

    console.print(table)


@app.command("approve")
def approve_task(
    task_id: str = typer.Argument(..., help="Task ID"),
    comment: Optional[str] = typer.Option(None, "--comment", "-c"),
):
    """Approve the pending step for a task."""
    client = DaemonClient()
    task = client.approve_task(task_id, comment)
    console.print(f"[green]Approved.[/green] Task state: {_styled_state(task['state'])}")
    _watch(client, task_id)


@app.command("reject")
def reject_task(
    task_id: str = typer.Argument(..., help="Task ID"),
    comment: Optional[str] = typer.Option(None, "--comment", "-c"),
):
    """Reject the pending step for a task."""
    client = DaemonClient()
    task = client.reject_task(task_id, comment)
    console.print(f"[red]Rejected.[/red] Task state: {_styled_state(task['state'])}")


@app.command("cancel")
def cancel_task(task_id: str = typer.Argument(..., help="Task ID")):
    """Cancel a running or pending task."""
    client = DaemonClient()
    client.cancel_task(task_id)
    console.print(f"Task [dim]{task_id}[/dim] cancelled.")
