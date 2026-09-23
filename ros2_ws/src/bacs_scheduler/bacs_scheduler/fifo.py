"""FIFO policy factory."""
from .scheduler import DutyCycleBudget, Scheduler
def create(budget: DutyCycleBudget) -> Scheduler:
    return Scheduler("FIFO", budget)
