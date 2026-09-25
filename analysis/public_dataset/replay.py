from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import DutyCycleBudget, Scheduler
from ros2_ws.src.bacs_scheduler.bacs_scheduler.sender_core import SENT, SenderCore

from .mrclam import DatasetCandidate


class _Clock:
    def __init__(self, start_ns: int) -> None:
        self.t = start_ns

    def __call__(self) -> int:
        return self.t


class _FakeRadio:
    def __init__(self, clock: _Clock) -> None:
        self.clock = clock

    def command(self, line: str, timeout_s: float = 2.0):
        now = self.clock()
        return now, now + 1_000_000, "+OK"


@dataclass(frozen=True)
class ReplayConfig:
    dataset_name: str = "MRCLAM"
    policies: tuple[str, ...] = ("FIFO", "BACS", "BACS+")
    robots: tuple[str, str] = ("robot1", "robot2")
    tick_hz: float = 5.0
    window_s: float = 60.0
    duty_cycle: float = 0.01
    trust_threshold: float = 0.05
    observability_weight: float = 0.30
    observability_reference: int = 6
    defer_half_life_s: float = 155.0
    max_queue_age_s: float = 600.0


@dataclass(frozen=True)
class ReplayResult:
    policy: str
    dataset: str
    session: str
    generated_candidates: int
    selected_candidates: int
    dropped_candidates: int
    airtime_s: float
    airtime_fraction_of_duty_budget: float
    selected_translation_rmse_m: float | None
    selected_yaw_rmse_rad: float | None


def _rmse(values: list[float]) -> float | None:
    return None if not values else math.sqrt(sum(v * v for v in values) / len(values))


def _run_policy(policy: str, candidates: list[DatasetCandidate], config: ReplayConfig) -> tuple[ReplayResult, list[dict[str, object]]]:
    start_ns = min(c.payload["t_gen_ns"] for c in candidates)
    end_ns = max(c.payload["t_gen_ns"] for c in candidates)
    tick_ns = max(int(1e9 / config.tick_hz), 1)
    clock = _Clock(start_ns)
    logs = {robot: io.StringIO() for robot in config.robots}
    cores = {
        robot: SenderCore(
            session=candidates[0].session,
            run=1,
            policy=policy,
            robot=robot,
            robots=list(config.robots),
            radio=_FakeRadio(clock),
            destination=100,
            log=logs[robot],
            clock_ns=clock,
            scheduler=Scheduler(policy, DutyCycleBudget(config.window_s, config.duty_cycle),
                                trust_threshold=config.trust_threshold,
                                observability_weight=config.observability_weight,
                                observability_reference=config.observability_reference,
                                defer_half_life_s=config.defer_half_life_s),
            max_queue_age_s=config.max_queue_age_s,
        ) for robot in config.robots
    }
    by_key = {(c.robot_i, c.payload["seq"]): c for c in candidates}
    next_tick = start_ns
    for candidate in candidates:
        while next_tick <= candidate.payload["t_gen_ns"]:
            clock.t = next_tick
            for core in cores.values():
                core.tick()
            next_tick += tick_ns
        clock.t = candidate.payload["t_gen_ns"]
        cores[candidate.robot_i].enqueue(candidate.payload)
    drain_deadline = end_ns + int(config.max_queue_age_s * 1e9)
    while any(core.queue for core in cores.values()) and next_tick <= drain_deadline:
        clock.t = next_tick
        for core in cores.values():
            core.tick()
        next_tick += tick_ns
    rows: list[dict[str, object]] = []
    for robot, core in cores.items():
        core.close()
        for row in csv.DictReader(io.StringIO(logs[robot].getvalue())):
            candidate = by_key.get((robot, int(row["seq"])))
            row["policy"] = policy
            row["dataset"] = config.dataset_name
            row["session"] = candidates[0].session
            row["translation_error_m"] = "" if candidate is None else candidate.translation_error_m
            row["yaw_error_rad"] = "" if candidate is None else candidate.yaw_error_rad
            rows.append(row)
    sent = [r for r in rows if r["status"] == SENT]
    duration_s = max((end_ns - start_ns) / 1e9, 1e-9)
    airtime_s = sum(float(r["airtime_s"]) for r in sent)
    errors = [float(r["translation_error_m"]) for r in sent if r["translation_error_m"] != ""]
    yaws = [float(r["yaw_error_rad"]) for r in sent if r["yaw_error_rad"] != ""]
    result = ReplayResult(
        policy=policy,
        dataset=config.dataset_name,
        session=candidates[0].session,
        generated_candidates=len(candidates),
        selected_candidates=len(sent),
        dropped_candidates=sum(r["status"] != SENT for r in rows),
        airtime_s=airtime_s,
        airtime_fraction_of_duty_budget=airtime_s / (config.duty_cycle * duration_s * len(config.robots)),
        selected_translation_rmse_m=_rmse(errors),
        selected_yaw_rmse_rad=_rmse(yaws),
    )
    return result, rows


def replay_dataset(candidates: list[DatasetCandidate], out_dir: Path, config: ReplayConfig = ReplayConfig()) -> list[ReplayResult]:
    if not config.policies:
        raise ValueError("ReplayConfig.policies must contain at least one policy.")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: list[ReplayResult] = []
    all_rows: list[dict[str, object]] = []
    for policy in config.policies:
        result, rows = _run_policy(policy, candidates, config)
        summary.append(result)
        all_rows.extend(rows)
        (out_dir / f"{config.dataset_name.lower()}_{policy.lower()}_summary.json").write_text(
            json.dumps(asdict(result), indent=2), encoding="utf-8"
        )
    if not summary:
        raise RuntimeError("Dataset replay produced no policy summaries.")
    with (out_dir / f"{config.dataset_name.lower()}_selected_candidates.csv").open("w", newline="", encoding="utf-8") as handle:
        if all_rows:
            writer = csv.DictWriter(handle, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
    with (out_dir / f"{config.dataset_name.lower()}_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(summary[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(row) for row in summary)
    (out_dir / f"{config.dataset_name.lower()}_config.json").write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    return summary
