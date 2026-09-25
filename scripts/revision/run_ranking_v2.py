#!/usr/bin/env python3
"""Ranking v2: trust-weighted, arrival-time and submodular ranking under the S8 protocol.

    python scripts/revision/run_ranking_v2.py --stage check    [--workers 20]
    python scripts/revision/run_ranking_v2.py --stage dev      [--workers 20]
    python scripts/revision/run_ranking_v2.py --stage test     [--workers 20] [--conditions nominal,...]
    python scripts/revision/run_ranking_v2.py --stage analyse

S8 setup throughout: 480 s sessions, N = 2, 3, 4, 5, deferral-derived gamma on every
arm, every arm on the same precomputed world per (seed, N, condition).

check    The new code (with diagnostics switched on) leaves existing arms unchanged:
         fifo, bacs_gated, plus_0.30_6 against the frozen S8 table and lifo, random,
         trust_only, info_only against the revision baselines, seeds 10-14.
dev      Seeds 0-9, nominal channel. Writes dev_raw.csv, dev_stale_info.csv and
         decision.md, which freezes ONE candidate (rule stated there).
test     Seeds 40-69 under each communication condition. Refuses to run unless
         decision.md exists and its recorded dev_raw.csv hash matches. Per-condition
         results go to parts/; analyse merges them.
analyse  test_raw.csv, test_summary.csv, test_paired_tests.csv, pooled_tests.csv,
         ladder_tests.csv, trust_yield.csv, stale_info.csv, stale_info_constraints.csv.gz,
         stress_benefit.csv, fig_ranking_v2.png, fig_stale_info.png, REPORT.md.

All outputs go to paper_results/revision/ranking_v2/.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bacs_sim.experiments import s8_config  # noqa: E402
from bacs_sim.simulator import precompute, run  # noqa: E402
from stats import describe, holm, paired  # noqa: E402

OUT = ROOT / "paper_results" / "revision" / "ranking_v2"
PARTS = OUT / "parts"
FROZEN = ROOT / "paper_results" / "simulation" / "frozen" / "s8_30seed_raw.csv"
BASELINES = ROOT / "paper_results" / "revision" / "baselines" / "raw.csv"

COUNTS, SESSION_S = (2, 3, 4, 5), 480.0
DEV_SEEDS, TEST_SEEDS, CHECK_SEEDS = range(0, 10), range(40, 70), range(10, 15)
CONTROLS = ["fifo", "lifo", "random", "trust_only", "info_only", "bacs_gated", "plus_0.30_6"]
# Ablation ladder. bacs_tw (TW on the base surrogate, no observability term) is
# reported but cannot be selected.
NEW = ["bacs_tw", "plus_tw", "plus_tw_arr", "plus_tw_arr_sub"]
SELECTABLE = ["plus_tw", "plus_tw_arr", "plus_tw_arr_sub"]
LADDER = [("plus_tw", "plus_0.30_6", "Does trust weighting help? (TW vs BACS+)"),
          ("plus_tw_arr", "plus_tw", "Does arrival-time trust help further? (TW-Arrival vs TW)"),
          ("plus_tw_arr_sub", "plus_tw_arr", "Does within-window diversity help further? (TW-Arrival-Sub vs TW-Arrival)"),
          ("plus_tw", "bacs_tw", "Does the observability term matter under TW? (TW on I+ vs TW on I)")]
DEV_ARMS = ["fifo", "random", "bacs_gated", "plus_0.30_6"] + NEW
TEST_ARMS = CONTROLS + NEW
REFERENCES = ["random", "plus_0.30_6", "fifo"]
# Fixed before DEV. The communication model is the paper's own (ChannelConfig);
# only its parameters change.
CONDITIONS = {
    "nominal": {},
    "loss_iid_0.2": dict(loss_model="independent", loss_rate=0.20),
    "burst_ge": dict(loss_model="burst"),            # Gilbert-Elliott at ChannelConfig defaults
    "delay_30s": dict(extra_delay_s=30.0),
}
BASE_COLS = ["condition", "n_robots", "seed", "arm", "align_rmse", "pose_rmse", "n_delivered", "trust_yield",
             "airtime_util", "n_sent"]
DIAG_COLS = ["age_sched", "age_send", "age_arrival", "theta_sched", "theta_arr_pred", "theta_server",
             "theta_temporal", "theta_spatial", "delta_theta", "I_plus", "I_tw_sched", "I_tw_arrival",
             "retention_delivered", "retention_sent", "eff_info_total", "pair_diversity"]
SUMMARY_METRICS = ["align_rmse", "pose_rmse", "trust_yield", "n_delivered", "airtime_util", "n_sent"]
TEST_METRICS = ["align_rmse", "pose_rmse"]
LABELS = {"fifo": "FIFO", "lifo": "LIFO", "random": "Random", "trust_only": "Trust-only",
          "info_only": "Info-only", "bacs_gated": "BACS", "plus_0.30_6": "BACS+ (0.30, 6)",
          "bacs_tw": "TW on I (no obs.)", "plus_tw": "TW", "plus_tw_arr": "TW-Arrival",
          "plus_tw_arr_sub": "TW-Arrival-Sub"}


# ---------------------------------------------------------------- simulation
def _run_summary(diag: list, n_robots: int) -> dict:
    d = pd.DataFrame(diag)
    if d.empty:
        return {k: np.nan for k in DIAG_COLS}
    dl = d[d.delivered]
    out = {k: float(dl[k].mean()) if len(dl) else np.nan
           for k in ["age_sched", "age_send", "age_arrival", "theta_sched", "theta_arr_pred", "theta_server",
                     "theta_temporal", "theta_spatial", "delta_theta", "I_plus", "I_tw_sched", "I_tw_arrival"]}
    out["retention_delivered"] = float(dl.retention.mean()) if len(dl) else np.nan
    out["retention_sent"] = float(d.retention.mean())          # lost packets retain nothing
    out["eff_info_total"] = float(dl.I_tw_arrival.sum())
    # Pair diversity: per (sender, window) with >= 2 deliveries, distinct peers
    # reached / the most that were possible. 1 = no pair repeated within a window.
    g = dl.groupby(["rid_from", "window"]).rid_to.agg(["nunique", "size"])
    g = g[g["size"] >= 2]
    out["pair_diversity"] = (float((g["nunique"] / np.minimum(g["size"], n_robots - 1)).mean())
                             if len(g) else np.nan)
    return out


def _cell(args):
    seed, n, arms, cond, keep_rows = args
    pre = None
    recs, rows = [], []
    for arm in arms:
        cfg = s8_config(arm, seed, n, SESSION_S)
        for k, v in CONDITIONS[cond].items():
            setattr(cfg.channel, k, v)
        if pre is None:
            pre = precompute(cfg)       # world depends on seed and N only
        r = run(cfg, precomputed=pre, collect_diag=True)
        diag = r.extras["diag"]
        recs.append(dict(condition=cond, n_robots=n, seed=seed, arm=arm, align_rmse=r.align_rmse,
                         pose_rmse=r.pose_rmse, n_delivered=r.n_delivered, trust_yield=r.trust_yield,
                         airtime_util=r.airtime_util, n_sent=r.n_sent, **_run_summary(diag, n)))
        if keep_rows:
            rows.extend(dict(condition=cond, n_robots=n, seed=seed, arm=arm, **x) for x in diag)
    return recs, rows


def simulate(seeds, arms, workers, cond="nominal", keep_rows=False):
    cells = [(s, n, tuple(arms), cond, keep_rows) for n in COUNTS for s in seeds]
    recs, rows = [], []
    with ProcessPoolExecutor(workers) as pool:
        for a, b in pool.map(_cell, cells):
            recs.extend(a)
            rows.extend(b)
    return pd.DataFrame(recs), pd.DataFrame(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(df: pd.DataFrame, name: str, base: Path = OUT) -> None:
    df.to_csv(base / name, index=False, lineterminator="\n")


def log_runtime(line: str) -> None:
    with open(OUT / "runtime.txt", "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


# --------------------------------------------------------------------- check
def stage_check(workers: int) -> int:
    ref = pd.concat([pd.read_csv(FROZEN).query("arm in ['fifo', 'bacs_gated', 'plus_0.30_6']").assign(source="frozen S8"),
                     pd.read_csv(BASELINES).query("arm in ['lifo', 'random', 'trust_only', 'info_only']")
                     .assign(source="revision baselines")])
    ref = ref[ref.seed.isin(CHECK_SEEDS)]
    t0 = time.time()
    raw, _ = simulate(CHECK_SEEDS, sorted(ref.arm.unique()), workers)
    log_runtime(f"check: {time.time() - t0:.1f} s with {workers} workers, {len(raw)} runs")
    m = ref.merge(raw, on=["n_robots", "seed", "arm"], suffixes=("_ref", "_new"), how="left")
    rows = []
    for (arm, src), a in m.groupby(["arm", "source"]):
        for metric in ("align_rmse", "pose_rmse", "trust_yield", "n_delivered"):
            diff = np.abs(a[f"{metric}_new"].to_numpy(float) - a[f"{metric}_ref"].to_numpy(float))
            tol = 0 if metric == "n_delivered" else 1e-12
            rows.append({"arm": arm, "reference": src, "metric": metric, "rows": len(a),
                         "max_abs_diff": float(np.nanmax(diff)),
                         "rows_outside_tolerance": int(np.sum(~(diff <= tol))), "tolerance": tol})
    check = pd.DataFrame(rows)
    write_csv(check, "frozen_check.csv")
    print(check.to_string(index=False))
    # bacs_gated carries ~2e-11 round-off against the frozen table on a few rows,
    # identical to paper_results/revision/baselines/frozen_check.csv (pre-existing).
    bad = check[(check.rows_outside_tolerance > 0) & ~((check.arm == "bacs_gated") & (check.max_abs_diff < 1e-9))]
    return int(len(bad) > 0)


# ----------------------------------------------------------------------- dev
def decide(dev: pd.DataFrame) -> tuple[str, str]:
    pooled = dev.groupby("arm").align_rmse.mean()
    chosen = min(SELECTABLE, key=lambda a: (pooled[a], a))
    agg = dev.groupby("arm")[["align_rmse", "pose_rmse", "trust_yield", "n_delivered", "age_arrival",
                              "retention_delivered", "pair_diversity"]].mean()
    L = ["# Ranking v2: DEV decision", "",
         f"Written {time.strftime('%Y-%m-%d %H:%M:%S')} from `dev_raw.csv` "
         f"(sha256 `{sha256(OUT / 'dev_raw.csv')}`), before any TEST seed was simulated.", "",
         "## Rule (fixed before DEV was run)", "",
         "1. Metric: DEV mean `align_rmse` pooled over all 40 seed-team pairs (seeds 0-9 x N = 2-5), nominal channel.",
         "2. Selectable: TW (`plus_tw`), TW-Arrival (`plus_tw_arr`), TW-Arrival-Sub (`plus_tw_arr_sub`). "
         "`bacs_tw` (TW without the observability term) is an ablation row only.",
         "3. Exactly one candidate is frozen: the lowest pooled DEV mean (ties broken by arm name). "
         "No threshold against the existing arms is applied.",
         "4. TEST (seeds 40-69) runs all controls and every ablation row under the four communication "
         "conditions fixed in the script before DEV: " + ", ".join(f"`{c}` {v or '(defaults)'}" for c, v in CONDITIONS.items()) + ".",
         "5. Confirmatory family: the frozen candidate on the nominal condition. Stress conditions and "
         "other rows are reported with their own Holm families.", "",
         "## DEV pooled means (40 pairs, nominal)", "",
         "| arm | label | align_rmse (m) | pose_rmse (m) | trust_yield | n_delivered | age at arrival (s) | retention | pair diversity |",
         "|---|---|---|---|---|---|---|---|---|"]
    for arm in sorted(DEV_ARMS, key=lambda a: agg.align_rmse[a]):
        r = agg.loc[arm]
        L.append(f"| `{arm}` | {LABELS[arm]} | {r.align_rmse:.4f} | {r.pose_rmse:.4f} | {r.trust_yield:.4f} | "
                 f"{r.n_delivered:.1f} | {r.age_arrival:.1f} | {r.retention_delivered:.3f} | {r.pair_diversity:.3f} |")
    L += ["", "## DEV means by N (align_rmse, m)", "", "| arm | " + " | ".join(f"N={n}" for n in COUNTS) + " |",
          "|---|" + "---|" * len(COUNTS)]
    byn = dev.pivot_table(index="arm", columns="n_robots", values="align_rmse", aggfunc="mean")
    for arm in DEV_ARMS:
        L.append(f"| `{arm}` | " + " | ".join(f"{byn.loc[arm, n]:.4f}" for n in COUNTS) + " |")
    vs = {r: 100 * (pooled[chosen] - pooled[r]) / pooled[r] for r in ("plus_0.30_6", "random")}
    L += ["", "## Decision", "", f"CHOSEN: {chosen}", "",
          f"`{chosen}` ({LABELS[chosen]}): DEV mean {pooled[chosen]:.4f} m, "
          f"{vs['plus_0.30_6']:+.1f} % vs plus_0.30_6, {vs['random']:+.1f} % vs random.", ""]
    return chosen, "\n".join(L)


def stage_dev(workers: int) -> int:
    t0 = time.time()
    dev, _ = simulate(DEV_SEEDS, DEV_ARMS, workers)
    write_csv(dev[BASE_COLS], "dev_raw.csv")
    write_csv(dev[["condition", "n_robots", "seed", "arm"] + DIAG_COLS], "dev_stale_info.csv")
    log_runtime(f"dev: {time.time() - t0:.1f} s with {workers} workers, {len(dev)} runs")
    chosen, md = decide(dev)
    (OUT / "decision.md").write_text(md, encoding="utf-8", newline="\n")
    print(md)
    return 0


# ---------------------------------------------------------------------- test
def read_decision() -> str:
    md = (OUT / "decision.md").read_text(encoding="utf-8")
    h = re.search(r"sha256 `([0-9a-f]{64})`", md).group(1)
    if h != sha256(OUT / "dev_raw.csv"):
        raise SystemExit("dev_raw.csv changed after decision.md was written")
    chosen = re.search(r"^CHOSEN: (\S+)$", md, re.M).group(1)
    assert chosen in SELECTABLE, chosen
    return chosen


def stage_test(workers: int, conditions) -> int:
    read_decision()                      # refuses to run without a frozen decision
    PARTS.mkdir(exist_ok=True)
    for cond in conditions:
        t0 = time.time()
        raw, rows = simulate(TEST_SEEDS, TEST_ARMS, workers, cond, keep_rows=True)
        write_csv(raw, f"test_raw_{cond}.csv", PARTS)
        rows.to_csv(PARTS / f"constraints_{cond}.csv.gz", index=False, lineterminator="\n",
                    float_format="%.6g", compression="gzip")
        log_runtime(f"test {cond}: {time.time() - t0:.1f} s with {workers} workers, {len(raw)} runs")
        print(f"{cond}: {len(raw)} runs in {time.time() - t0:.1f} s", flush=True)
    return 0


# ------------------------------------------------------------------ analysis
def role_of(arm, chosen):
    return "confirmatory" if arm == chosen else ("ablation" if arm in NEW else "context")


def summarise(raw: pd.DataFrame, metrics) -> pd.DataFrame:
    rows = []
    for (cond, arm), g in raw.groupby(["condition", "arm"], sort=False):
        for metric in metrics:
            for n in COUNTS:
                rows.append({"condition": cond, "n_robots": str(n), "policy": arm, "metric": metric,
                             **describe(g[g.n_robots == n][metric])})
            rows.append({"condition": cond, "n_robots": "all", "policy": arm, "metric": metric,
                         **describe(g[metric])})
    return pd.DataFrame(rows)


def _wide(d, metric):
    return d.pivot_table(index=["seed", "n_robots"], columns="arm", values=metric)


def compare(raw: pd.DataFrame, chosen, pooled: bool) -> pd.DataFrame:
    rows = []
    for cond, dc in raw.groupby("condition", sort=False):
        groups = [("all", dc)] if pooled else [(str(n), dc[dc.n_robots == n]) for n in COUNTS]
        for metric in TEST_METRICS:
            for ref in REFERENCES:
                for label, d in groups:
                    w = _wide(d, metric)
                    for arm in TEST_ARMS:
                        if arm != ref:
                            rows.append({"condition": cond, "metric": metric, "reference": ref, "n_robots": label,
                                         "policy": arm, "role": role_of(arm, chosen),
                                         **paired(w[arm].to_numpy(), w[ref].to_numpy())})
    return _holm(pd.DataFrame(rows), ["condition", "metric", "reference", "role"])


def ladder(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cond, dc in raw.groupby("condition", sort=False):
        for metric in TEST_METRICS:
            for a, b, q in LADDER:
                for label, d in [("all", dc)] + [(str(n), dc[dc.n_robots == n]) for n in COUNTS]:
                    w = _wide(d, metric)
                    rows.append({"condition": cond, "metric": metric, "question": q, "policy": a, "reference": b,
                                 "n_robots": label, **paired(w[a].to_numpy(), w[b].to_numpy())})
    out = pd.DataFrame(rows)
    out["scope"] = np.where(out.n_robots == "all", "pooled", "per_N")
    return _holm(out, ["condition", "metric", "scope"])


def _holm(out, keys):
    out["holm_family"] = out[keys].astype(str).agg(" | ".join, axis=1)
    out["p_holm"] = np.nan
    for _, idx in out.groupby("holm_family").groups.items():
        out.loc[idx, "p_holm"] = holm(out.loc[idx, "wilcoxon_p_two_sided"])
    return out


def pct_ci(d: pd.DataFrame, arm: str, ref: str, metric="align_rmse"):
    """Paired mean difference as % of the reference mean, with a t-based 95 % CI."""
    w = _wide(d, metric)
    diff = (w[arm] - w[ref]).to_numpy()
    base = w[ref].mean()
    half = sps.t.ppf(0.975, len(diff) - 1) * diff.std(ddof=1) / np.sqrt(len(diff))
    return 100 * diff.mean() / base, 100 * (diff.mean() - half) / base, 100 * (diff.mean() + half) / base


INK, MUTED, GRID, ACCENT, ABL = "#1f1e1d", "#73726c", "#e2e2e0", "#1baf7a", "#2a78d6"


def _style(ax):
    ax.grid(axis="x", color=GRID, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)


def _color(arm, chosen):
    return ACCENT if arm == chosen else (ABL if arm in NEW else MUTED)


def figure(raw: pd.DataFrame, chosen, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    nom = raw[raw.condition == "nominal"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.0), dpi=150, gridspec_kw=dict(width_ratios=[1, 1, 1.05]))
    for ax, ref in zip(axes[:2], ["plus_0.30_6", "random"]):
        order = [a for a in TEST_ARMS if a != ref]
        for y, arm in enumerate(order):
            c = _color(arm, chosen)
            m, lo, hi = pct_ci(nom, arm, ref)
            ax.plot([lo, hi], [y, y], color=c, lw=2, solid_capstyle="round", zorder=3)
            ax.plot(m, y, "o", ms=8, color=c, mec="white", mew=2, zorder=4)
            for k, n in enumerate(COUNTS):
                ax.plot(pct_ci(nom[nom.n_robots == n], arm, ref)[0], y - 0.24 + 0.16 * k, "|", ms=6,
                        color=c, alpha=0.55, zorder=2)
        ax.axvline(0, color=INK, lw=1, zorder=1)
        ax.set_yticks(range(len(order)), [LABELS[a] for a in order], fontsize=8.5, color=INK)
        for t, arm in zip(ax.get_yticklabels(), order):
            t.set_fontweight("bold" if arm == chosen else "normal")
        ax.set_xlabel(f"Nominal: paired change in align_rmse vs {LABELS[ref]} (%)", fontsize=9, color=INK)
        ax.set_ylim(len(order) - 0.5, -0.5)
        _style(ax)
    # Stress panel: chosen candidate vs the two references, per condition.
    ax = axes[2]
    conds = list(CONDITIONS)
    for k, (ref, mk) in enumerate([("plus_0.30_6", "o"), ("random", "s")]):
        for y, cond in enumerate(conds):
            m, lo, hi = pct_ci(raw[raw.condition == cond], chosen, ref)
            yy = y + (k - 0.5) * 0.3
            ax.plot([lo, hi], [yy, yy], color=ACCENT if k == 0 else INK, lw=2, solid_capstyle="round", zorder=3)
            ax.plot(m, yy, mk, ms=7, color=ACCENT if k == 0 else INK, mec="white", mew=1.5, zorder=4,
                    label=f"vs {LABELS[ref]}" if y == 0 else None)
    ax.axvline(0, color=INK, lw=1, zorder=1)
    ax.set_yticks(range(len(conds)), conds, fontsize=8.5, color=INK)
    ax.set_ylim(len(conds) - 0.5, -0.5)
    ax.set_xlabel(f"{LABELS[chosen]}: paired change in align_rmse (%)", fontsize=9, color=INK)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    _style(ax)
    fig.suptitle("Ranking v2, TEST seeds 40-69 (120 seed-team pairs per condition). Dot = pooled paired mean, "
                 "bar = 95 % t-CI, ticks = per-N means (N = 2..5 top to bottom). Negative = lower error.\n"
                 f"Green = DEV-frozen candidate ({LABELS[chosen]}); blue = other ablation rows; grey = existing arms.",
                 x=0.01, ha="left", fontsize=9, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path)
    plt.close(fig)


def figure_stale(stale: pd.DataFrame, chosen, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = stale[(stale.condition == "nominal") & (stale.n_robots == "all")]
    panels = [("age_arrival", "Age at arrival (s)"), ("theta_server", "Server trust at arrival"),
              ("retention_delivered", "Effective-information retention"), ("pair_diversity", "Within-window pair diversity")]
    fig, axes = plt.subplots(1, 4, figsize=(14, 4.4), dpi=150, sharey=True)
    for ax, (metric, title) in zip(axes, panels):
        r = s[s.metric == metric].set_index("policy").loc[TEST_ARMS]
        for y, arm in enumerate(TEST_ARMS):
            c = _color(arm, chosen)
            ax.plot([r.loc[arm, "ci95_lo"], r.loc[arm, "ci95_hi"]], [y, y], color=c, lw=2, zorder=3)
            ax.plot(r.loc[arm, "mean"], y, "o", ms=7, color=c, mec="white", mew=1.5, zorder=4)
        ax.set_title(title, fontsize=9, color=INK, loc="left")
        _style(ax)
    axes[0].set_yticks(range(len(TEST_ARMS)), [LABELS[a] for a in TEST_ARMS], fontsize=8.5, color=INK)
    axes[0].set_ylim(len(TEST_ARMS) - 0.5, -0.5)
    fig.suptitle("Stale-information diagnostics, nominal TEST: mean over delivered constraints per run, "
                 "then mean and 95 % t-CI over 120 runs", x=0.01, ha="left", fontsize=9, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path)
    plt.close(fig)


def _fmt(r):
    return (f"{r.pct_change_of_mean:+.1f} %, d = {r.cliffs_delta:+.2f}, {r.seeds_won}/{r.n_pairs} wins, "
            f"p_Holm = {r.p_holm:.2g}")


def per_window(cons: pd.DataFrame) -> pd.DataFrame:
    """Packets sent per (sender, window), nominal TEST, by N: the room the ranking has to act in."""
    from bacs_sim.config import LoRaConfig
    from bacs_sim.lora import airtime_budget
    d = cons[cons.condition == "nominal"]
    k = d.groupby(["n_robots", "arm", "seed", "rid_from", "window"]).size().rename("k").reset_index()
    rows = []
    for n, g in k.groupby("n_robots"):
        rows.append(dict(n_robots=n, budget_s=airtime_budget(60.0, LoRaConfig(), n),
                         t_air_mean_s=float(d[d.n_robots == n].t_air.mean()),
                         sent_per_sender_window_mean=float(g.k.mean()),
                         share_windows_with_1=float((g.k == 1).mean()),
                         share_windows_with_2plus=float((g.k >= 2).mean())))
    return pd.DataFrame(rows)


def report(raw, summary, tests, pooled, lad, stale, stress, chosen, pw) -> str:
    runtime = (OUT / "runtime.txt").read_text(encoding="utf-8").strip().splitlines()
    L = ["# Ranking v2: trust-weighted, arrival-time and submodular ranking (S8 protocol)", "",
         "## What was run", "",
         "- S8 setup: 480 s sessions, N = 2, 3, 4, 5, deferral-derived gamma on every arm, all arms on the "
         "same precomputed world per (seed, N, condition).",
         "- New rows (`bacs_sim/schedulers.py`), all with bacs_gated's gate (theta_hat >= 0.05), budget, expiry "
         "and greedy packing:",
         "  - **TW** `plus_tw`: rank by I_tw / T_air, I_tw = 0.5 log(1 + theta_hat (exp(2 I+) - 1)), "
         "I+ = BACS+ surrogate (w_o = 0.30, n_ref = 6). `bacs_tw` is the same on the base surrogate I.",
         "  - **TW-Arrival** `plus_tw_arr`: theta_hat inside I_tw replaced by theta_hat x exp(-gamma x a_c), "
         "a_c = age already accumulated at the decision. theta_hat itself already carries the predicted "
         "future delay (deferral + queue + airtime + retries); the server scores the full age, so a_c was "
         "the missing term. The gate still uses theta_hat.",
         "  - **TW-Arrival-Sub** `plus_tw_arr_sub`: TW-Arrival with in-window diminishing returns: after each "
         "pick n_ij is provisionally incremented, the pick's cell marked in a copy of the coverage map, and "
         "the remaining candidates rescored.",
         "- `frozen_check.csv`: with the new code and diagnostics switched on, fifo/bacs_gated/plus_0.30_6 reproduce "
         "the frozen S8 table and lifo/random/trust_only/info_only the revision baselines (seeds 10-14; "
         "bacs_gated's ~2e-11 round-off is the same as in `baselines/frozen_check.csv`). "
         "The diagnostics only read state.",
         f"- DEV (seeds 0-9, nominal) froze **{LABELS[chosen]}** (`{chosen}`) before TEST; see `decision.md`.",
         "- TEST: seeds 40-69 x N = 2-5 = 120 pairs per arm per condition; conditions (fixed before DEV): "
         + "; ".join(f"`{c}` {v or 'ChannelConfig defaults'}" for c, v in CONDITIONS.items()) + ".",
         "- Runtime: " + "; ".join(runtime), "",
         "## Structural constraint on what any ranking can do", "",
         "| N | per-robot budget per 60 s window (s) | mean T_air (s) | packets per sender-window | share with >= 2 |",
         "|---|---|---|---|---|"]
    for _, r in pw.iterrows():
        L.append(f"| {r.n_robots} | {r.budget_s:.3f} | {r.t_air_mean_s:.3f} | {r.sent_per_sender_window_mean:.2f} | "
                 f"{r.share_windows_with_2plus:.2f} |")
    L += ["", "At N >= 3 each sender transmits one constraint per window, and at N = 2 two constraints to its "
          "only peer. Every policy therefore delivers the same number of constraints (nominal channel); the "
          "ranking decides only which constraint goes out. Within-window diminishing returns can act only at "
          "N = 2, and only through coverage novelty, so TW-Arrival-Sub equals TW-Arrival at N >= 3 by "
          "construction. For the same reason the pair-diversity diagnostic is uninformative here.", "",
         "## Confirmatory result: nominal, pooled over 120 pairs (align_rmse)", "",
         "| policy | role | mean (m) | 95 % CI | vs random | vs plus_0.30_6 | vs fifo |", "|---|---|---|---|---|---|---|"]
    s = summary[(summary.metric == "align_rmse") & (summary.n_robots == "all") & (summary.condition == "nominal")]
    s = s.set_index("policy")
    pt = pooled[(pooled.metric == "align_rmse") & (pooled.condition == "nominal")].set_index(["policy", "reference"])
    for arm in sorted(TEST_ARMS, key=lambda a: s.loc[a, "mean"]):
        r = s.loc[arm]
        cells = ["-" if arm == ref else _fmt(pt.loc[(arm, ref)]) for ref in ("random", "plus_0.30_6", "fifo")]
        name = f"**{LABELS[arm]}** (`{arm}`)" if arm == chosen else f"{LABELS[arm]} (`{arm}`)"
        L.append(f"| {name} | {role_of(arm, chosen)} | {r['mean']:.4f} | [{r.ci95_lo:.4f}, {r.ci95_hi:.4f}] | "
                 + " | ".join(cells) + " |")
    L += ["", "Two-sided paired Wilcoxon; Cliff's d < 0 and wins = row policy lower. Holm within "
          "(condition, metric, reference, role); the confirmatory family holds only the frozen candidate.", "",
          "## Frozen candidate by team size (nominal, align_rmse)", "",
          "| reference | N | % change | Cliff's d | wins | p (raw) | p_Holm |", "|---|---|---|---|---|---|---|"]
    t = tests[(tests.metric == "align_rmse") & (tests.role == "confirmatory") & (tests.condition == "nominal")]
    for _, r in t.iterrows():
        L.append(f"| {r.reference} | {r.n_robots} | {r.pct_change_of_mean:+.1f} % | {r.cliffs_delta:+.2f} | "
                 f"{r.seeds_won}/{r.n_pairs} | {r.wilcoxon_p_two_sided:.2g} | {r.p_holm:.2g} |")
    L += ["", "## Ablation ladder (align_rmse, pooled 120 pairs, Holm within condition)", "",
          "| question | " + " | ".join(CONDITIONS) + " |", "|---|" + "---|" * len(CONDITIONS)]
    lp = lad[(lad.metric == "align_rmse") & (lad.n_robots == "all")]
    for a, b, q in LADDER:
        L.append(f"| {q} | " + " | ".join(
            _fmt(lp[(lp.policy == a) & (lp.reference == b) & (lp.condition == c)].iloc[0]) for c in CONDITIONS) + " |")
    L += ["", "## Communication stress: frozen candidate (align_rmse, pooled)", "",
          "| condition | mean age at arrival, candidate (s) | mean age at arrival, random (s) | vs random | vs plus_0.30_6 |",
          "|---|---|---|---|---|"]
    for _, r in stress.iterrows():
        L.append(f"| {r.condition} | {r.age_arrival_candidate:.1f} | {r.age_arrival_random:.1f} | "
                 f"{r.pct_vs_random:+.1f} % (p_Holm {r.p_holm_vs_random:.2g}) | "
                 f"{r.pct_vs_plus:+.1f} % (p_Holm {r.p_holm_vs_plus:.2g}) |")
    L += ["", "Hypothesis: the benefit of trust-aware ranking grows with staleness risk. Stress rows are "
          "secondary (Holm within each condition, not across conditions).", "",
          "## Stale-information diagnostics (nominal, pooled means over 120 runs)", "",
          "| policy | age at send (s) | age at arrival (s) | theta sched | theta arrival (server) | delta theta | "
          "retention (delivered) | retention (sent) | pair diversity | trust_yield | n_delivered | airtime util |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    sn = stale[(stale.condition == "nominal") & (stale.n_robots == "all")].pivot(index="policy", columns="metric", values="mean")
    sm = summary[(summary.condition == "nominal") & (summary.n_robots == "all")].pivot(index="policy", columns="metric", values="mean")
    for arm in TEST_ARMS:
        r, q = sn.loc[arm], sm.loc[arm]
        L.append(f"| {LABELS[arm]} | {r.age_send:.1f} | {r.age_arrival:.1f} | {r.theta_sched:.3f} | {r.theta_server:.3f} | "
                 f"{r.delta_theta:+.3f} | {r.retention_delivered:.3f} | {r.retention_sent:.3f} | {r.pair_diversity:.3f} | "
                 f"{q.trust_yield:.3f} | {q.n_delivered:.1f} | {q.airtime_util:.3f} |")
    L += ["", "Retention = I_tw(I+, server theta at arrival) / I+ per constraint (lost packets count 0 in the "
          "'sent' column). delta theta = scheduling-time theta_hat minus server theta. Pair diversity = distinct "
          "peers reached / possible, per sender-window with >= 2 deliveries (always 1 at N = 2).", "",
          "## Secondary metric: pose_rmse (nominal, pooled, frozen candidate)", ""]
    pp = pooled[(pooled.metric == "pose_rmse") & (pooled.role == "confirmatory") & (pooled.condition == "nominal")]
    for _, r in pp.iterrows():
        L.append(f"- vs {r.reference}: {_fmt(r)}")
    L += ["", "## Files", "",
          "`frozen_check.csv`, `dev_raw.csv`, `dev_stale_info.csv`, `decision.md`, `test_raw.csv` (per run, all "
          "conditions, with per-run diagnostic means), `test_summary.csv` (mean, SD, 95 % t-CI per condition x "
          "policy x N and pooled), `test_paired_tests.csv` (per N), `pooled_tests.csv` (120 pairs), "
          "`ladder_tests.csv`, `trust_yield.csv`, `stale_info.csv`, `stale_info_constraints.csv.gz` (one row per "
          "transmitted constraint), `stress_benefit.csv`, `fig_ranking_v2.png`, `fig_stale_info.png`, "
          "`runtime.txt`, `parts/` (per-condition raw).", ""]
    return "\n".join(L)


def analyse() -> int:
    chosen = read_decision()
    conds = [c for c in CONDITIONS if (PARTS / f"test_raw_{c}.csv").exists()]
    raw = pd.concat([pd.read_csv(PARTS / f"test_raw_{c}.csv") for c in conds], ignore_index=True)
    write_csv(raw, "test_raw.csv")
    cons = pd.concat([pd.read_csv(PARTS / f"constraints_{c}.csv.gz") for c in conds], ignore_index=True)
    cons.to_csv(
        OUT / "stale_info_constraints.csv.gz", index=False, lineterminator="\n", float_format="%.6g",
        compression="gzip")
    summary = summarise(raw, SUMMARY_METRICS)
    write_csv(summary, "test_summary.csv")
    write_csv(summary[summary.metric == "trust_yield"].drop(columns="metric"), "trust_yield.csv")
    stale = summarise(raw, DIAG_COLS)
    write_csv(stale, "stale_info.csv")
    tests = compare(raw, chosen, pooled=False)
    write_csv(tests, "test_paired_tests.csv")
    pooled = compare(raw, chosen, pooled=True)
    write_csv(pooled, "pooled_tests.csv")
    lad = ladder(raw)
    write_csv(lad, "ladder_tests.csv")
    rows = []
    for c in conds:
        d = raw[raw.condition == c]
        p = pooled[(pooled.condition == c) & (pooled.metric == "align_rmse") & (pooled.policy == chosen)].set_index("reference")
        rows.append(dict(condition=c, candidate=chosen,
                         age_arrival_candidate=d[d.arm == chosen].age_arrival.mean(),
                         age_arrival_random=d[d.arm == "random"].age_arrival.mean(),
                         pct_vs_random=p.loc["random", "pct_change_of_mean"], p_holm_vs_random=p.loc["random", "p_holm"],
                         pct_vs_plus=p.loc["plus_0.30_6", "pct_change_of_mean"], p_holm_vs_plus=p.loc["plus_0.30_6", "p_holm"],
                         pct_vs_fifo=p.loc["fifo", "pct_change_of_mean"], p_holm_vs_fifo=p.loc["fifo", "p_holm"]))
    stress = pd.DataFrame(rows)
    write_csv(stress, "stress_benefit.csv")
    figure(raw, chosen, OUT / "fig_ranking_v2.png")
    figure_stale(stale, chosen, OUT / "fig_stale_info.png")
    pw = per_window(cons)
    write_csv(pw, "packets_per_window.csv")
    (OUT / "REPORT.md").write_text(report(raw, summary, tests, pooled, lad, stale, stress, chosen, pw),
                                   encoding="utf-8", newline="\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["check", "dev", "test", "analyse"], required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "check":
        return stage_check(args.workers)
    if args.stage == "dev":
        return stage_dev(args.workers)
    if args.stage == "test":
        conds = args.conditions.split(",")
        assert set(conds) <= set(CONDITIONS), conds
        return stage_test(args.workers, conds)
    return analyse()


if __name__ == "__main__":
    sys.exit(main())
