"""Deterministic, explicitly simulated scheduling experiments."""

from __future__ import annotations

import csv
import random
from pathlib import Path

from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import Constraint, DutyCycleBudget, Scheduler


def experiment(seed: int, robots: int, policy: str, temporal_decay: bool = True) -> dict[str, float | int | str]:
    """Simulate candidate selection; no output is physical evidence."""
    rng = random.Random(seed)
    candidates = [
        Constraint(i, i * 100_000_000, 52, rng.random(), rng.random(), "r0", f"r{i % robots}",
                   rng.randrange(0, 12))
        for i in range(240)
    ]
    scheduler = Scheduler(policy, DutyCycleBudget(), defer_half_life_s=60.0 if temporal_decay else 1e12)
    selected = scheduler.select(candidates, 60_000_000_000)
    return {"seed": seed, "robots": robots, "policy": policy, "temporal_decay": temporal_decay,
            "candidates": len(candidates), "selected": len(selected),
            "mean_information": sum(x.information_score for x in selected) / len(selected) if selected else 0.0}


def write_outputs(root: Path) -> None:
    raw = root / "paper_results" / "simulation" / "raw"; summary = root / "paper_results" / "simulation" / "summary"
    raw.mkdir(parents=True, exist_ok=True); summary.mkdir(parents=True, exist_ok=True)
    rows = [experiment(seed, robots, policy) for seed in range(10, 40) for robots in range(2, 6)
            for policy in ("FIFO", "BACS", "BACS+")]
    rows += [experiment(seed, 2, "BACS+", temporal_decay=False) for seed in range(10, 40)]
    with (raw / "s8_seed_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    groups: dict[tuple[str, int, bool], list[float]] = {}
    for row in rows:
        groups.setdefault((str(row["policy"]), int(row["robots"]), bool(row["temporal_decay"])), []).append(float(row["mean_information"]))
    with (summary / "simulation_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["policy", "robots", "temporal_decay", "n_seeds", "mean_information"])
        writer.writeheader()
        for (policy, robots, decay), values in sorted(groups.items()):
            writer.writerow({"policy": policy, "robots": robots, "temporal_decay": decay, "n_seeds": len(values),
                             "mean_information": sum(values) / len(values)})
    s7c = [experiment(seed, 2, "BACS+") for seed in range(10, 40)]
    s9 = [experiment(seed, 2, "BACS+", temporal_decay=decay) for seed in range(10, 40) for decay in (True, False)]
    ablations = [experiment(seed, 3, policy) for seed in range(10, 40) for policy in ("FIFO", "BACS", "BACS+")]
    for filename, records in (("s7c_incremental_information.csv", s7c), ("s9_temporal_decay.csv", s9),
                              ("ablations.csv", ablations)):
        with (raw / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
