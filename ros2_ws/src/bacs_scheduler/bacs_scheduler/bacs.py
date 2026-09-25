"""BACS policy factory."""
from .scheduler import DutyCycleBudget, Scheduler
def create(budget: DutyCycleBudget, trust_threshold: float = .05) -> Scheduler:
    return Scheduler("BACS", budget, trust_threshold=trust_threshold)
