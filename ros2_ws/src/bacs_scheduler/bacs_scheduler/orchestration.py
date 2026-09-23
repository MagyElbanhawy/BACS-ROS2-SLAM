"""Experiment-session lifecycle interface."""
from typing import Protocol
class ExperimentOrchestrator(Protocol):
    def start_run(self, session: str, run: int) -> None: ...
