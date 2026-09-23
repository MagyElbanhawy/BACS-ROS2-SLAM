"""Pairwise observability calculation."""
from math import exp
def pairwise(constraint_count: int, reference: int = 6) -> float:
    if reference <= 0: raise ValueError("reference must be positive")
    return exp(-constraint_count / reference)
