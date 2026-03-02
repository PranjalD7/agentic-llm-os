from pydantic import BaseModel


class StepSpec(BaseModel):
    """Produced by the planner; consumed by the policy engine and DB writer."""
    order: int
    description: str
    command: str
