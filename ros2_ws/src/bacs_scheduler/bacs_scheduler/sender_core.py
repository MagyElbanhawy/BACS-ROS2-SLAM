"""Robot-side transmit loop: queue candidates, pick one per radio slot, log every outcome.

One radio, one packet at a time: a candidate is sent only when the previous
``AT+SEND`` has been answered and the rolling duty-cycle budget has room for
its airtime. Every candidate gets exactly one row in the candidate log with its
final status; nothing is written for events that did not happen.
"""

from __future__ import annotations

import csv
import threading
import time
from dataclasses import dataclass
from typing import IO, Any, Callable, Protocol

from .rylr998 import ON_AIR_BYTES, ConstraintPayload, send_command
from .scheduler import Constraint, DutyCycleBudget, Scheduler, lora_airtime_s

CANDIDATE_LOG_FIELDS = [
    "session", "run", "policy", "robot", "seq", "robot_i", "robot_j", "kf_i", "kf_j", "t_gen_ns", "t_enqueued_ns",
    "t_selected_ns", "t_cmd_ns", "t_ok_ns", "radio_response", "payload_bytes", "airtime_s",
    "predicted_trust", "information_score", "pair_constraints", "queue_length", "rank_time_us", "status",
]
# status values
SENT, RADIO_ERROR, RADIO_TIMEOUT = "SENT", "RADIO_ERROR", "RADIO_TIMEOUT"
REJECTED_TRUST, DROPPED_AGE, PENDING_AT_END = "REJECTED_TRUST", "DROPPED_AGE", "PENDING_AT_END"


class Radio(Protocol):
    def command(self, line: str, timeout_s: float = 2.0) -> tuple[int, int | None, str]: ...


@dataclass
class Pending:
    constraint: Constraint
    payload: ConstraintPayload
    row: dict[str, Any]


class SenderCore:
    def __init__(self, *, session: str, run: int, policy: str, robot: str, robots: list[str], radio: Radio,
                 destination: int, log: IO[str], clock_ns: Callable[[], int], scheduler: Scheduler | None = None,
                 max_queue_age_s: float = 600.0, response_timeout_s: float = 2.0) -> None:
        self.session, self.run, self.policy, self.robot = session, run, policy, robot
        self.robot_index = {name: i for i, name in enumerate(robots)}
        self.radio, self.destination, self.clock_ns = radio, destination, clock_ns
        self.scheduler = scheduler or Scheduler(policy, DutyCycleBudget())
        self.max_queue_age_ns = int(max_queue_age_s * 1e9)
        self.response_timeout_s = response_timeout_s
        self.airtime_s = lora_airtime_s(ON_AIR_BYTES)
        self.queue: dict[int, Pending] = {}
        self.lock = threading.Lock()
        self.writer = csv.DictWriter(log, fieldnames=CANDIDATE_LOG_FIELDS, lineterminator="\n")
        self.writer.writeheader()
        self.log = log

    def enqueue(self, candidate: dict[str, Any]) -> None:
        """Add a candidate from the front-end (see docs/HARDWARE_EXPERIMENT_V2.md for fields)."""
        now = self.clock_ns()
        seq = int(candidate["seq"])
        if not 0 <= seq <= 0xFFFF:
            raise ValueError(f"seq {seq} does not fit the 16-bit payload field")
        constraint = Constraint(seq, int(candidate["t_gen_ns"]), ON_AIR_BYTES, float(candidate["predicted_trust"]),
                                float(candidate["information_score"]), candidate["robot_i"], candidate["robot_j"],
                                int(candidate.get("pair_constraints", 0)))
        payload = ConstraintPayload(seq, self.robot_index[candidate["robot_i"]], self.robot_index[candidate["robot_j"]],
                                    float(candidate["dx"]), float(candidate["dy"]), float(candidate["dtheta"]),
                                    float(candidate["var_x"]), float(candidate["var_y"]), float(candidate["var_theta"]),
                                    constraint.predicted_trust, constraint.information_score,
                                    int(candidate["kf_i"]), int(candidate["kf_j"]), constraint.generated_ns // 1_000_000)
        row = {"session": self.session, "run": self.run, "policy": self.policy, "robot": self.robot, "seq": seq,
               "robot_i": constraint.robot_i, "robot_j": constraint.robot_j, "kf_i": payload.kf_i,
               "kf_j": payload.kf_j, "t_gen_ns": constraint.generated_ns,
               "t_enqueued_ns": now, "payload_bytes": ON_AIR_BYTES, "airtime_s": self.airtime_s,
               "predicted_trust": constraint.predicted_trust, "information_score": constraint.information_score,
               "pair_constraints": constraint.pair_constraints}
        with self.lock:
            if seq in self.queue:
                raise ValueError(f"duplicate candidate seq {seq}")
            if constraint.predicted_trust < self.scheduler.trust_threshold:
                self._finish(Pending(constraint, payload, row), REJECTED_TRUST)
            else:
                self.queue[seq] = Pending(constraint, payload, row)

    def tick(self) -> str | None:
        """Drop over-age candidates, then send at most one packet. Returns the status of a send."""
        with self.lock:
            now = self.clock_ns()
            for seq in [s for s, p in self.queue.items() if now - p.constraint.generated_ns > self.max_queue_age_ns]:
                self._finish(self.queue.pop(seq), DROPPED_AGE)
            started = time.perf_counter_ns()
            ordered = self.scheduler.rank([p.constraint for p in self.queue.values()], now)
            rank_time_us = (time.perf_counter_ns() - started) / 1000
            if not ordered or not self.scheduler.budget.can_send(now / 1e9, self.airtime_s):
                return None
            item = self.queue.pop(ordered[0].sequence)
            item.row.update({"t_selected_ns": now, "queue_length": len(self.queue) + 1, "rank_time_us": rank_time_us})
            t_cmd, t_resp, response = self.radio.command(send_command(self.destination, item.payload.encode()),
                                                         self.response_timeout_s)
            item.row.update({"t_cmd_ns": t_cmd, "t_ok_ns": t_resp if t_resp is not None else "",
                             "radio_response": response})
            if response == "+OK":
                status = SENT
            elif response == "TIMEOUT":
                status = RADIO_TIMEOUT
            else:
                status = RADIO_ERROR
            if status != RADIO_ERROR:  # a timeout may still have transmitted: charge it to stay legal
                self.scheduler.budget.record(t_cmd / 1e9, self.airtime_s)
            self._finish(item, status)
            return status

    def close(self) -> None:
        with self.lock:
            for seq in sorted(self.queue):
                self._finish(self.queue.pop(seq), PENDING_AT_END)
            self.log.flush()

    def _finish(self, item: Pending, status: str) -> None:
        self.writer.writerow({**item.row, "status": status})
        self.log.flush()
