"""RYLR998 LoRa module: payload codec, AT-line parsing and a timestamped serial link.

Nothing here invents a measurement. Every timestamp is the system clock
(``time.time_ns``, keep it chrony/PTP-synchronised across machines) read when a
line is written to or read from the UART, and every RSSI/SNR value is parsed
from a ``+RCV`` line emitted by the receiving module.

AT reference (Reyax RYLR998): commands end with CRLF; ``AT+SEND=<addr>,<len>,<data>``
answers ``+OK`` or ``+ERR=<n>``; a received packet is reported as
``+RCV=<addr>,<len>,<data>,<rssi>,<snr>``.
"""

from __future__ import annotations

import base64
import csv
import queue
import struct
import threading
import time
from dataclasses import dataclass
from typing import IO, Callable, Protocol

# 39 bytes -> exactly 52 base64 characters on air (no padding, no ',' or CR/LF).
PAYLOAD_FORMAT = "<IBBffffffeeIx"
PAYLOAD_STRUCT = struct.Struct(PAYLOAD_FORMAT)
ON_AIR_BYTES = 52
assert PAYLOAD_STRUCT.size == 39


@dataclass(frozen=True)
class ConstraintPayload:
    """What one packet carries. ``gen_ms`` is the low 32 bits of t_gen in ms."""

    seq: int
    robot_i: int
    robot_j: int
    dx: float
    dy: float
    dtheta: float
    var_x: float
    var_y: float
    var_theta: float
    predicted_trust: float
    information_score: float
    gen_ms: int

    def encode(self) -> str:
        raw = PAYLOAD_STRUCT.pack(self.seq & 0xFFFFFFFF, self.robot_i, self.robot_j, self.dx, self.dy,
                                  self.dtheta, self.var_x, self.var_y, self.var_theta, self.predicted_trust,
                                  self.information_score, self.gen_ms & 0xFFFFFFFF)
        return base64.b64encode(raw).decode("ascii")

    @classmethod
    def decode(cls, text: str) -> "ConstraintPayload":
        return cls(*PAYLOAD_STRUCT.unpack(base64.b64decode(text.encode("ascii"), validate=True)))


@dataclass(frozen=True)
class Received:
    address: int
    length: int
    data: str
    rssi_dbm: int
    snr_db: int


def send_command(address: int, data: str) -> str:
    if not 0 < len(data) <= 240:
        raise ValueError("RYLR998 payload must be 1-240 bytes")
    if any(c in data for c in "\r\n"):
        raise ValueError("payload must not contain CR/LF")
    return f"AT+SEND={address},{len(data)},{data}"


def parse_rcv(line: str) -> Received | None:
    """Parse ``+RCV=<addr>,<len>,<data>,<rssi>,<snr>``; data may itself contain commas."""
    if not line.startswith("+RCV="):
        return None
    address, length, rest = line[5:].split(",", 2)
    n = int(length)
    data, tail = rest[:n], rest[n:]
    if not tail.startswith(","):
        raise ValueError(f"malformed +RCV line: {line!r}")
    rssi, snr = tail[1:].split(",")
    return Received(int(address), n, data, int(rssi), int(snr))


class SerialPort(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def readline(self) -> bytes: ...


class TraceWriter:
    """Append-only transcript of every UART line: ``t_ns, direction, line``."""

    def __init__(self, handle: IO[str]) -> None:
        self._lock = threading.Lock()
        self._handle = handle
        self._writer = csv.writer(handle, lineterminator="\n")
        self._writer.writerow(["t_ns", "direction", "line"])

    def record(self, t_ns: int, direction: str, line: str) -> None:
        with self._lock:
            self._writer.writerow([t_ns, direction, line])
            self._handle.flush()


class Rylr998Link:
    """Line-oriented link. A reader thread timestamps every incoming line.

    ``+RCV`` lines go to ``on_receive(t_ns, Received)``; all other lines are
    queued as command responses for :meth:`command`.
    """

    def __init__(self, port: SerialPort, trace: TraceWriter | None = None,
                 on_receive: Callable[[int, Received], None] | None = None,
                 clock_ns: Callable[[], int] = time.time_ns) -> None:
        self.port, self.trace, self.on_receive, self.clock_ns = port, trace, on_receive, clock_ns
        self.responses: "queue.Queue[tuple[int, str]]" = queue.Queue()
        self._write_lock = threading.Lock()
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while self._running:
            raw = self.port.readline()
            if not raw:
                continue
            t_ns = self.clock_ns()
            line = raw.decode("ascii", errors="replace").strip()
            if not line:
                continue
            if self.trace:
                self.trace.record(t_ns, "rx", line)
            received = parse_rcv(line)
            if received is not None:
                if self.on_receive:
                    self.on_receive(t_ns, received)
            else:
                self.responses.put((t_ns, line))

    def command(self, line: str, timeout_s: float = 2.0) -> tuple[int, int | None, str]:
        """Write one AT command; return (t_written_ns, t_response_ns, response)."""
        with self._write_lock:
            while not self.responses.empty():  # drop stale responses
                self.responses.get_nowait()
            self.port.write((line + "\r\n").encode("ascii"))
            t_written = self.clock_ns()
            if self.trace:
                self.trace.record(t_written, "tx", line)
            try:
                t_response, response = self.responses.get(timeout=timeout_s)
            except queue.Empty:
                return t_written, None, "TIMEOUT"
            return t_written, t_response, response

    def configure(self, commands: list[str]) -> list[tuple[str, str]]:
        """Send configuration commands and return (command, response) pairs for the log."""
        return [(c, self.command(c)[2]) for c in commands]

    def close(self) -> None:
        self._running = False


def configuration_commands(address: int, network_id: int, band_hz: int = 868_000_000, sf: int = 7,
                           bw_code: int = 7, cr_code: int = 1, preamble: int = 8, power_dbm: int = 14) -> list[str]:
    """AT commands for the experiment, followed by read-backs so the log holds what the module reports.

    ``bw_code`` 7 = 125 kHz (8 = 250 kHz, 9 = 500 kHz); ``cr_code`` 1 = 4/5.
    A preamble other than 12 requires NETWORKID 18.
    """
    return [
        "AT", f"AT+ADDRESS={address}", f"AT+NETWORKID={network_id}", f"AT+BAND={band_hz}",
        f"AT+PARAMETER={sf},{bw_code},{cr_code},{preamble}", f"AT+CRFOP={power_dbm}",
        "AT+ADDRESS?", "AT+NETWORKID?", "AT+BAND?", "AT+PARAMETER?", "AT+CRFOP?", "AT+VER?", "AT+UID?",
    ]


def expected_readback(address: int, network_id: int, band_hz: int = 868_000_000, sf: int = 7, bw_code: int = 7,
                      cr_code: int = 1, preamble: int = 8, power_dbm: int = 14) -> dict[str, str]:
    """Replies the module must give to the read-back queries of :func:`configuration_commands`."""
    return {"AT+ADDRESS?": f"+ADDRESS={address}", "AT+NETWORKID?": f"+NETWORKID={network_id}",
            "AT+BAND?": f"+BAND={band_hz}", "AT+PARAMETER?": f"+PARAMETER={sf},{bw_code},{cr_code},{preamble}",
            "AT+CRFOP?": f"+CRFOP={power_dbm}"}


def readback_mismatches(replies: list[tuple[str, str]], expected: dict[str, str]) -> list[str]:
    """Commands whose reply was an error/timeout, or whose read-back differs from ``expected``."""
    got = dict(replies)
    problems = [f"{c} -> {r}" for c, r in replies if r == "TIMEOUT" or r.startswith("+ERR")]
    problems += [f"{q} -> {got.get(q, 'NO REPLY')} (expected {want})"
                 for q, want in expected.items() if got.get(q, "").replace(" ", "") != want]
    return problems
