"""Interface for received fusion feedback."""
from typing import Protocol
class FusionFeedback(Protocol):
    def update_trust(self, constraint_id: str, accepted: bool) -> None: ...
