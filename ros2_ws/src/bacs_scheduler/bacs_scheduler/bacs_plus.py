"""Observability-aware BACS+ policy factory."""
from .scheduler import DutyCycleBudget, Scheduler
def create(budget: DutyCycleBudget, trust_threshold: float = .5, observability_weight: float = .30) -> Scheduler:
    return Scheduler("BACS+", budget, trust_threshold=trust_threshold, observability_weight=observability_weight)
