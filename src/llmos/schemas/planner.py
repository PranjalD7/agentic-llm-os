from pydantic import BaseModel


class StepSpec(BaseModel):
    """Produced by the planner; consumed by the policy engine and DB writer."""
    order: int
    description: str
    command: str


class PlannerResponse(BaseModel):
    """
    Response from the iterative planner (plan_next / fix_step).
    When done=True, the task is complete and step fields are ignored.
    """
    done: bool
    order: int = 0
    description: str = ""
    command: str = ""
