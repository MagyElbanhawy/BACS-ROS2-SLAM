"""RYLR998 transport interface; hardware I/O is supplied by a ROS node."""
from typing import Protocol
class Rylr998Transport(Protocol):
    def transmit(self, payload: bytes) -> None: ...
