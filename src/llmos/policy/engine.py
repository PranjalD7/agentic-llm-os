import re
from dataclasses import dataclass
from typing import Optional

from ..schemas.enums import RiskLevel
from .rules import BLOCKED_PATTERNS, RISKY_PATTERNS


@dataclass
class PolicyVerdict:
    risk_level: RiskLevel
    reason: str
    transformed_command: Optional[str] = None  # None → use original command


class PolicyEngine:
    """
    Evaluates a shell command string and returns a PolicyVerdict.
    BLOCKED is checked before RISKY; everything else is SAFE.
    """

    def evaluate(self, command: str) -> PolicyVerdict:
        for pattern, reason in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return PolicyVerdict(risk_level=RiskLevel.BLOCKED, reason=reason)

        for pattern, reason in RISKY_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return PolicyVerdict(risk_level=RiskLevel.RISKY, reason=reason)

        return PolicyVerdict(
            risk_level=RiskLevel.SAFE,
            reason="Command passed all policy checks",
        )
