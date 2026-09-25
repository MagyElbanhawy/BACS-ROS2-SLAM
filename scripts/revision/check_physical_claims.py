#!/usr/bin/env python3
"""Re-run the physical timing/radio pipeline and check the physical claims.

    python scripts/revision/check_physical_claims.py

Runs ``analysis.physical.pipeline.physical_analysis`` on hardware/raw/HWS-002/003/005
in a temporary root (so paper_results/physical is not overwritten), copies the
regenerated summaries to paper_results/revision/physical/, reports whether they are
byte-identical to the committed ones, and writes physical_claims_check.csv.
"""
from __future__ import annotations

import filecmp
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analysis.physical.pipeline import physical_analysis  # noqa: E402

OUT = ROOT / "paper_results" / "revision" / "physical"
FILES = ["timing_summary.csv", "radio_summary.csv", "session_counts.csv", "timing_per_packet.csv", "radio_per_run.csv"]
COPIED = FILES[:3]  # per-packet/per-run tables are only compared, not duplicated
POLICIES = ["FIFO", "BACS", "BACS+"]
# claim -> ({policy: paper value}, rounding digits). A float digits value < 1 is
# instead an absolute tolerance (used for the approximate "airtime ~10 %" claim).
CLAIMS = {
    "median_deferral_sent_s": ({"FIFO": 153.5, "BACS": 141.9, "BACS+": 166.1}, 1),
    "median_channel_delay_s": ({"FIFO": 0.170, "BACS": 0.170, "BACS+": 0.171}, 3),
    "deferral_channel_ratio": ({"FIFO": 902, "BACS": 835, "BACS+": 973}, 0),
    "packets_sent_per_session": ({"FIFO": 141, "BACS": 139, "BACS+": 137}, 0),
    "airtime_fraction_of_duty_budget_mean": ({"FIFO": 0.10, "BACS": 0.10, "BACS+": 0.10}, 0.01),
    "airtime_fraction_of_duty_budget_median": ({"FIFO": 0.10, "BACS": 0.10, "BACS+": 0.10}, 0.01),
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / "hardware").symlink_to(ROOT / "hardware")
        (tmp_root / "config").symlink_to(ROOT / "config")
        physical_analysis(tmp_root)
        fresh = tmp_root / "paper_results" / "physical"
        identical = {}
        for name in FILES:
            if name in COPIED:
                shutil.copyfile(fresh / name, OUT / name)
            identical[name] = filecmp.cmp(fresh / name, ROOT / "paper_results" / "physical" / name, shallow=False)
    timing = pd.read_csv(OUT / "timing_summary.csv").set_index(["policy", "metric"])
    radio = pd.read_csv(OUT / "radio_summary.csv").set_index(["policy", "metric"])
    counts = pd.read_csv(OUT / "session_counts.csv").set_index("policy")
    rows = []
    for policy in POLICIES:
        deferral = timing.loc[(policy, "deferral_sent_s"), "median"]
        channel = timing.loc[(policy, "channel_delay_s"), "median"]
        computed = {
            "median_deferral_sent_s": deferral,
            "median_channel_delay_s": channel,
            "deferral_channel_ratio": deferral / channel,
            "packets_sent_per_session": counts.loc[policy, "packets_sent_per_session"],
            "airtime_fraction_of_duty_budget_mean": radio.loc[(policy, "airtime_fraction_of_duty_budget"), "mean"],
            "airtime_fraction_of_duty_budget_median": radio.loc[(policy, "airtime_fraction_of_duty_budget"), "median"],
        }
        for claim, (papers, digits) in CLAIMS.items():
            paper = papers[policy]
            value = float(computed[claim])
            if isinstance(digits, float):
                rule, match = f"abs diff <= {digits}", abs(value - paper) <= digits
            else:
                rule, match = f"round to {digits} dp", round(value, digits) == round(paper, digits)
            rows.append({"claim": claim, "policy": policy, "paper_value": paper, "computed": value,
                         "rule": rule, "match": bool(match)})
    check = pd.DataFrame(rows)
    check.to_csv(OUT / "physical_claims_check.csv", index=False, lineterminator="\n")
    with (OUT / "reproduction_status.txt").open("w", encoding="utf-8") as handle:
        for name, same in identical.items():
            handle.write(f"{name}: {'IDENTICAL to' if same else 'DIFFERS from'} paper_results/physical/{name}\n")
    print(check.to_string(index=False))
    print("\n".join(f"{n}: {'identical' if s else 'DIFFERS'}" for n, s in identical.items()))
    return 0 if check["match"].all() and all(identical.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
