import httpx

from ..config import settings


class DaemonClient:
    def __init__(self):
        self.base_url = f"http://{settings.daemon_host}:{settings.daemon_port}"

    def _check_daemon(self):
        try:
            httpx.get(f"{self.base_url}/health", timeout=2)
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to llmos daemon at {self.base_url}\n"
                f"Start it with: llmos-daemon"
            )

    def create_task(self, intent: str) -> dict:
        self._check_daemon()
        r = httpx.post(f"{self.base_url}/tasks", json={"intent": intent}, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_task(self, task_id: str) -> dict:
        r = httpx.get(f"{self.base_url}/tasks/{task_id}", timeout=10)
        r.raise_for_status()
        return r.json()

    def list_tasks(self) -> list:
        self._check_daemon()
        r = httpx.get(f"{self.base_url}/tasks", timeout=10)
        r.raise_for_status()
        return r.json()

    def approve_task(self, task_id: str, comment: str = None) -> dict:
        r = httpx.post(
            f"{self.base_url}/tasks/{task_id}/approve",
            json={"decision": "APPROVED", "comment": comment},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def reject_task(self, task_id: str, comment: str = None) -> dict:
        r = httpx.post(
            f"{self.base_url}/tasks/{task_id}/reject",
            json={"decision": "REJECTED", "comment": comment},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def cancel_task(self, task_id: str) -> dict:
        r = httpx.delete(f"{self.base_url}/tasks/{task_id}", timeout=10)
        r.raise_for_status()
        return r.json()
