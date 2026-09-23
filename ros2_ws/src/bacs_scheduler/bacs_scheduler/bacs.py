"""BACS policy factory."""
from .scheduler import DutyCycleBudget, Scheduler
def create(budget: DutyCycleBudget, trust_threshold: float = .5) -> Scheduler:
    return Scheduler("BACS", budget, trust_threshold=trust_threshold)
