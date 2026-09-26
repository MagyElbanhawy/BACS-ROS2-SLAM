#!/usr/bin/env python3
"""Build paper_results/revision/REPORT.md from the revision-v3 CSVs.

    python scripts/revision/make_report.py [--pytest "49 passed in 2.8s"]

Every number in the report's tables is read from paper_results/revision/*; the
narrative sections are fixed text in this script.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "paper_results" / "revision"
ARMS = ["fifo", "lifo", "random", "trust_only", "info_only", "bacs_gated", "plus_0.30_6"]
LABEL = {"fifo": "FIFO", "lifo": "LIFO", "random": "Random", "trust_only": "Trust-only", "info_only": "Info-only",
         "bacs_gated": "BACS", "plus_0.30_6": "BACS+ (0.30, 6)"}
RULES = ["fixed 0.003", "drift derived", "drift adaptive", "deferral derived", "deferral adaptive"]


def table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def p_fmt(p: float) -> str:
    if pd.isna(p):
        return "n/a"
    return f"{p:.2e}" if p < 1e-3 else f"{p:.4f}"


def physical() -> str:
    c = pd.read_csv(REV / "physical" / "physical_claims_check.csv")
    rows = [[r.claim, r.policy, r.paper_value, f"{r.computed:.6g}", r.rule, "yes" if r.match else "NO"] for r in c.itertuples()]
    status = (REV / "physical" / "reproduction_status.txt").read_text().strip().splitlines()
    return (table(["claim", "policy", "paper", "recomputed", "rule", "match"], rows)
            + "\n\nRegenerated pipeline outputs vs committed:\n\n" + "\n".join(f"- {s}" for s in status))


def baselines() -> str:
    d = REV / "baselines"
    s = pd.read_csv(d / "summary.csv")
    parts = []
    for metric, title, fmt in (("align_rmse", "Map-alignment RMSE (m), mean ± SD [95 % CI]", "{:.3f}"),
                               ("pose_rmse", "Pose RMSE (m), mean ± SD [95 % CI]", "{:.3f}"),
                               ("n_delivered", "Delivered constraints, mean ± SD", "{:.1f}")):
        rows = []
        for arm in ARMS:
            row = [LABEL[arm]]
            for n in (2, 3, 4, 5):
                r = s[(s.metric == metric) & (s.policy == arm) & (s.n_robots == n)].iloc[0]
                txt = f"{fmt.format(r['mean'])} ± {fmt.format(r.sd)}"
                if metric != "n_delivered":
                    txt += f" [{fmt.format(r.ci95_lo)}, {fmt.format(r.ci95_hi)}]"
                row.append(txt)
            rows.append(row)
        parts.append(f"**{title}**\n\n" + table(["policy", "N=2", "N=3", "N=4", "N=5"], rows))
    t = pd.read_csv(d / "paired_tests.csv")
    for ref in ("fifo", "plus_0.30_6"):
        x = t[(t.metric == "align_rmse") & (t.reference == ref)]
        rows = [[LABEL[r.policy], r.n_robots, f"{r.pct_change_of_mean:+.1f} %", p_fmt(r.wilcoxon_p_two_sided),
                 p_fmt(r.p_holm), f"{r.cliffs_delta:+.2f}", f"{r.seeds_won}/30" + (f" ({r.seeds_tied} tied)" if r.seeds_tied else "")]
                for r in x.itertuples()]
        parts.append(f"**Map-alignment RMSE, each policy vs {LABEL[ref]}** (negative change / δ = policy lower; "
                     f"won = seeds where the policy is lower; Holm over the 24 tests vs {LABEL[ref]})\n\n"
                     + table(["policy", "N", "Δ mean", "Wilcoxon p (2-sided)", "Holm p", "Cliff's δ", "won"], rows))
    f = pd.read_csv(d / "frozen_check.csv")
    rows = [[r.arm, r.metric, r.rows, f"{r.max_abs_diff:.1e}", r.rows_outside_tolerance] for r in f.itertuples()]
    parts.append("**Reproduction of the frozen S8 table**\n\n"
                 + table(["arm", "metric", "rows", "max abs diff", "rows outside tolerance"], rows))
    return "\n\n".join(parts)


def decay() -> str:
    d = REV / "decay"
    s = pd.read_csv(d / "summary.csv")
    parts = []
    for metric, title in (("align_rmse", "Map-alignment RMSE (m)"), ("pose_rmse", "Pose RMSE (m)")):
        rows = []
        for rule in RULES:
            row = [rule]
            for n in (2, 3, 4, 5):
                r = s[(s.rule == rule) & (s.n_robots == n)].iloc[0]
                row.append(f"{r[f'{metric}_mean']:.3f} ± {r[f'{metric}_sd']:.3f} "
                           f"[{r[f'{metric}_ci95_lo']:.3f}, {r[f'{metric}_ci95_hi']:.3f}]")
            rows.append(row)
        parts.append(f"**{title}, mean ± SD [95 % CI]**\n\n" + table(["rule", "N=2", "N=3", "N=4", "N=5"], rows))
    rows = []
    for rule in RULES:
        row = [rule]
        for n in (2, 3, 4, 5):
            r = s[(s.rule == rule) & (s.n_robots == n)].iloc[0]
            row.append(f"{r.gamma_mean:.4f} ± {r.gamma_sd:.4f}")
        rows.append(row)
    parts.append("**γ used (1/s; final value of the run, mean ± SD over seeds)**\n\n"
                 + table(["rule", "N=2", "N=3", "N=4", "N=5"], rows))
    t = pd.read_csv(d / "paired_tests.csv")
    for metric, title in (("align_rmse", "map-alignment RMSE"), ("pose_rmse", "pose RMSE")):
        x = t[t.metric == metric]
        rows = [[r.versus, r.n_robots, f"{r.pct_change_of_mean:+.1f} %", p_fmt(r.wilcoxon_p_two_sided), p_fmt(r.p_holm),
                 f"{r.cliffs_delta:+.2f}", f"{r.seeds_deferral_derived_lower}/30"] for r in x.itertuples()]
        parts.append(f"**Deferral-derived vs each other rule, {title}** (Δ and δ negative = deferral-derived lower; "
                     "Holm over the 16 tests for this metric)\n\n"
                     + table(["vs", "N", "Δ mean", "Wilcoxon p (2-sided)", "Holm p", "Cliff's δ", "deferral-derived lower"], rows))
    f = pd.read_csv(d / "frozen_check.csv")
    parts.append(f"**Reproduction of the frozen S9 table** (seeds 0-4, N = 2): max abs diff over "
                 f"{len(f)} cells = {f.abs_diff.max():.1e}.")
    return "\n\n".join(parts)


def runtime(name: str) -> str:
    return (REV / name / "runtime.txt").read_text().strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pytest", default="not recorded")
    args = ap.parse_args()
    body = TEMPLATE.format(physical=physical(), baselines=baselines(), decay=decay(),
                           rt_base=runtime("baselines"), rt_decay=runtime("decay"), pytest=args.pytest)
    (REV / "REPORT.md").write_text(body, encoding="utf-8")
    print(f"wrote {(REV / 'REPORT.md').relative_to(ROOT)}")


TEMPLATE = open(Path(__file__).with_name("report_template.md"), encoding="utf-8").read()

if __name__ == "__main__":
    main()
