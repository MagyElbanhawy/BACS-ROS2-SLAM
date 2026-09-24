#!/usr/bin/env python3
"""Render the reproducibility report from generated CSVs.

Draft-manuscript values live in ``paper_results/paper_claims.csv`` and are only
compared against, never used to compute anything.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
PHYSICAL = ROOT / "paper_results" / "physical"
TOLERANCE = 0.05  # relative difference still reported as MATCH


def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pick(records: list[dict[str, str]], column: str, **where: str) -> float | None:
    found = next((r for r in records if all(r.get(k) == v for k, v in where.items())), None)
    try:
        return float(found[column]) if found and found.get(column) not in (None, "") else None
    except ValueError:
        return None


def main() -> None:
    timing, radio = rows(PHYSICAL / "timing_summary.csv"), rows(PHYSICAL / "radio_summary.csv")
    counts = rows(PHYSICAL / "session_counts.csv")
    map_summary, map_stats = rows(PHYSICAL / "map_alignment_summary.csv"), rows(PHYSICAL / "map_alignment_statistics.csv")
    fifo_plus = {"reference": "FIFO", "candidate": "BACS+"}
    sim_tests = rows(ROOT / "paper_results" / "simulation" / "s8_paired_tests.csv")
    sim_source_file = ROOT / "paper_results" / "simulation" / "s8_source.txt"
    sim_source = sim_source_file.read_text(encoding="utf-8").strip() if sim_source_file.exists() else "not run"
    plus_vs_fifo = [r for r in sim_tests if r["arm_a"] == "plus_0.30_6" and r["arm_b"] == "fifo"
                    and r["metric"] == "align_rmse"]

    def sim(n: int, column: str) -> float | None:
        return pick(plus_vs_fifo, column, n_robots=str(n))

    def sim_range(fn) -> float | None:
        values = [float(r["improvement_pct"]) for r in plus_vs_fifo]
        return fn(values) if values else None

    def sim_pose_min_p() -> float | None:
        pairs = {("bacs_gated", "fifo"), ("plus_0.30_6", "fifo"), ("plus_0.60_5", "fifo"), ("plus_0.30_6", "bacs_gated")}
        values = [float(r["wilcoxon_p"]) for r in sim_tests if r["metric"] == "pose_rmse"
                  and (r["arm_a"], r["arm_b"]) in pairs and r["wilcoxon_p"] not in ("", "nan")]
        return min(values) if values else None

    def ratio() -> float | None:
        deferral = pick(timing, "median", policy="BACS+", metric="deferral_sent_s")
        channel = pick(timing, "median", policy="BACS+", metric="channel_delay_s")
        return deferral / channel if deferral and channel else None

    def neg(value: float | None) -> float | None:
        return -value if value is not None else None

    recomputed: dict[str, tuple[Callable[[], float | None], str]] = {
        "map_rmse_fifo": (lambda: pick(map_summary, "mean_m", policy="FIFO"), "map_alignment_summary.csv"),
        "map_rmse_bacs": (lambda: pick(map_summary, "mean_m", policy="BACS"), "map_alignment_summary.csv"),
        "map_rmse_bacsplus": (lambda: pick(map_summary, "mean_m", policy="BACS+"), "map_alignment_summary.csv"),
        "map_improvement": (lambda: neg(pick(map_stats, "relative_change_of_means", **fifo_plus)), "map_alignment_statistics.csv"),
        "map_wilcoxon_p": (lambda: pick(map_stats, "wilcoxon_paired_p_one_sided_less", **fifo_plus), "map_alignment_statistics.csv"),
        "map_cliffs_delta": (lambda: pick(map_stats, "cliffs_delta", **fifo_plus), "map_alignment_statistics.csv"),
        "age_fifo": (lambda: pick(timing, "median", policy="FIFO", metric="packet_age_s"), "timing_summary.csv"),
        "deferral_fifo": (lambda: pick(timing, "median", policy="FIFO", metric="deferral_sent_s"), "timing_summary.csv"),
        "channel_fifo": (lambda: pick(timing, "median", policy="FIFO", metric="channel_delay_s"), "timing_summary.csv"),
        "age_bacsplus": (lambda: pick(timing, "median", policy="BACS+", metric="packet_age_s"), "timing_summary.csv"),
        "deferral_bacsplus": (lambda: pick(timing, "median", policy="BACS+", metric="deferral_sent_s"), "timing_summary.csv"),
        "channel_bacsplus": (lambda: pick(timing, "median", policy="BACS+", metric="channel_delay_s"), "timing_summary.csv"),
        "deferral_channel_ratio": (ratio, "timing_summary.csv"),
        "generated_per_session": (lambda: pick(counts, "packets_generated_per_session", policy="BACS+"), "session_counts.csv"),
        "sent_per_run": (lambda: pick(counts, "packets_sent_per_run_median", policy="BACS+"), "session_counts.csv"),
        "airtime_bacsplus": (lambda: pick(radio, "median", policy="BACS+", metric="airtime_fraction_of_duty_budget"), "radio_summary.csv"),
        "sim_reduction_min": (lambda: sim_range(min), "simulation/s8_paired_tests.csv"),
        "sim_reduction_max": (lambda: sim_range(max), "simulation/s8_paired_tests.csv"),
        "sim_reduction_n5": (lambda: sim(5, "improvement_pct"), "simulation/s8_paired_tests.csv"),
        "sim_p_n5": (lambda: sim(5, "wilcoxon_p"), "simulation/s8_paired_tests.csv"),
        "sim_delta_n5": (lambda: sim(5, "cliffs_delta"), "simulation/s8_paired_tests.csv"),
        **{f"sim_wins_n{n}": ((lambda n=n: sim(n, "seeds_a_lower")), "simulation/s8_paired_tests.csv") for n in (2, 3, 4, 5)},
        "sim_pose_min_p": (sim_pose_min_p, "simulation/s8_paired_tests.csv"),
    }

    lines = []
    for claim in rows(ROOT / "paper_results" / "paper_claims.csv"):
        compute, source = recomputed[claim["claim_id"]]
        paper, value = float(claim["paper_value"]), compute()
        if value is None or math.isnan(value):
            status, shown, diff = "NOT_COMPUTABLE", "N/A", "N/A"
        else:
            rel = abs(value - paper) / abs(paper)
            if claim.get("check") == "greater_than":
                status, diff = ("MATCH" if value > paper else "MISMATCH"), f"> {paper:g}?"
            else:
                status, diff = ("MATCH" if rel <= TOLERANCE else "MISMATCH"), f"{rel:.1%}"
            shown = f"{value:.4g}"
        lines.append(f"| {claim['description']} | {claim['paper_value']} {claim['unit']} | {shown} | {diff} | "
                     f"{status} | `{source}` | {claim['manuscript_location']} |")

    mismatches = sum("| MISMATCH |" in line for line in lines)
    report = f"""# Reproducibility report

Generated by `scripts/update_report.py` from the CSVs in `paper_results/physical/` and `paper_results/simulation/`. Simulation source: {sim_source}. Draft-manuscript values are read from `paper_results/paper_claims.csv` and are compared only; nothing is fitted to them. MATCH means within {TOLERANCE:.0%} relative difference. Metric definitions: `docs/METRIC_DEFINITIONS.md`. Open data-quality questions: `REPRODUCIBILITY_ISSUES.md`.

| Claim | Draft paper | Recomputed | Rel. diff. | Status | Source | Manuscript |
|---|---:|---:|---:|---|---|---|
{chr(10).join(lines)}

{mismatches} claim(s) do not match the data. The manuscript must be updated to the recomputed values (or the discrepancy explained) before submission.

Map-alignment rows stay NOT_COMPUTABLE until `paper_results/physical/fused/fused_<session>.csv` exist for every session (see `docs/REPRODUCTION_GUIDE.md`, steps 2-4).
"""
    (ROOT / "REPRODUCIBILITY_REPORT.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
