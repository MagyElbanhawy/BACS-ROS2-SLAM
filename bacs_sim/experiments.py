"""
Scenario runners.  Each returns a pandas DataFrame ready for the manuscript.

S1  scheduling policy comparison
S2  airtime budget sweep
S3  channel robustness
S4  decay coefficient study (tests H1)
S5  utility ablation
S6  scalability (tests H3)
S7  information-surrogate validation (Spearman rho vs exact MI)
S8  observability ablation (BACS vs BACS+ across team size)
S9  decay-coefficient rule comparison (deferral vs drift derivations)
"""
import numpy as np
import pandas as pd
from dataclasses import replace

from .config import SimConfig
from .simulator import run, precompute, _odometry_information
from .trust import gamma_derived, gamma_deferral_derived
from .infogain import exact_info_from_cov, rank_correlation
from .schedulers import POLICIES


def _mk(seed=0, n_robots=2, **over):
    c = SimConfig()
    c.seed = seed
    c.world.n_robots = n_robots
    for k, v in over.items():
        obj, attr = k.split(".", 1)
        setattr(getattr(c, obj), attr, v)
    return c


def _agg(records, by):
    df = pd.DataFrame(records)
    g = df.groupby(by).agg(["mean", "std"])
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    return g.reset_index()


def _sweep(configs, seeds, n_robots=2, label_fn=None):
    """Run every config across every seed on shared world data."""
    recs = []
    for s in seeds:
        base = _mk(seed=s, n_robots=n_robots)
        pre = precompute(base)
        for cfg in configs:
            c = replace(cfg)
            c.seed = s
            c.world.n_robots = n_robots
            r = run(c, precomputed=pre)
            rec = dict(seed=s, pose_rmse=r.pose_rmse, align_rmse=r.align_rmse,
                       trust_yield=r.trust_yield, accept_rate=r.accept_rate,
                       airtime_util=r.airtime_util, n_delivered=r.n_delivered,
                       bytes_sent=r.bytes_sent, starvation=r.starvation,
                       sched_ms=r.sched_overhead_ms, outlier_share=r.outlier_share,
                       gamma=r.gamma_final, dt_bias=r.dt_pred_bias)
            rec.update(label_fn(cfg) if label_fn else {})
            recs.append(rec)
    return recs


# ------------------------------------------------------------------------ S1
def s1_policy_comparison(seeds=range(5), policies=None):
    policies = policies or POLICIES
    cfgs = []
    for p in policies:
        c = SimConfig()
        c.scheduler.policy = p
        cfgs.append(c)
    recs = _sweep(cfgs, seeds, label_fn=lambda c: dict(policy=c.scheduler.policy))
    return _agg(recs, "policy")


# ------------------------------------------------------------------------ S2
def s2_budget_sweep(seeds=range(3), duty=(0.001, 0.005, 0.01, 0.05), policies=("fifo", "bacs_gated")):
    cfgs = []
    for d in duty:
        for p in policies:
            c = SimConfig()
            c.lora.duty_cycle = d
            c.scheduler.policy = p
            cfgs.append(c)
    # unconstrained arm, carrying H4
    for p in policies:
        c = SimConfig()
        c.scheduler.policy = p
        c.scheduler.unlimited_budget = True
        c.lora.duty_cycle = 1.0
        cfgs.append(c)
    recs = _sweep(cfgs, seeds, label_fn=lambda c: dict(
        duty=c.lora.duty_cycle if not c.scheduler.unlimited_budget else np.inf,
        policy=c.scheduler.policy))
    return _agg(recs, ["duty", "policy"])


# ------------------------------------------------------------------------ S3
def s3_channel(seeds=range(3), policies=("fifo", "bacs_gated")):
    conds = [("ideal", "independent", 0.0, 0.0),
             ("delay_0.2", "independent", 0.0, 0.2),
             ("loss_10", "independent", 0.10, 0.0),
             ("loss_30", "independent", 0.30, 0.0),
             ("burst_30", "burst", 0.30, 0.0),
             ("worst", "burst", 0.30, 0.2)]
    cfgs = []
    for name, model, loss, dly in conds:
        for p in policies:
            c = SimConfig()
            c.channel.loss_model = model
            c.channel.loss_rate = loss
            c.channel.extra_delay_s = dly
            c.scheduler.policy = p
            c.__dict__["_cond"] = name
            cfgs.append(c)
    recs = _sweep(cfgs, seeds, label_fn=lambda c: dict(
        condition=c.__dict__.get("_cond"), policy=c.scheduler.policy))
    return _agg(recs, ["condition", "policy"])


# ------------------------------------------------------------------------ S4
def s4_gamma(seeds=range(3), gammas=(0.001, 0.003, 0.005, 0.01, 0.03, 0.10, 0.30),
             policy="bacs_gated"):
    """Tests H1: does Eq. (16) predict the empirical optimum?"""
    cfgs = []
    for g in gammas:
        c = SimConfig()
        c.trust.gamma = g
        c.trust.gamma_rule = "fixed"
        c.scheduler.policy = policy
        cfgs.append(c)
    for rule in ("derived", "adaptive"):
        c = SimConfig()
        c.trust.gamma_rule = rule
        c.scheduler.policy = policy
        cfgs.append(c)
    recs = _sweep(cfgs, seeds, label_fn=lambda c: dict(
        gamma_setting=(f"{c.trust.gamma:.3f}" if c.trust.gamma_rule == "fixed"
                       else c.trust.gamma_rule)))
    out = _agg(recs, "gamma_setting")
    base = SimConfig()
    out.attrs["gamma_star"] = gamma_derived(base.world, base.trust)
    return out


# ------------------------------------------------------------------------ S5
def s5_ablation(seeds=range(5)):
    """Utility ablation. Each row removes one factor from Eq. (13)."""
    variants = [
        ("full BACS (gated)",      dict(policy="bacs_gated")),
        ("multiplicative Eq.(13)", dict(policy="bacs")),
        ("trust term only",        dict(policy="greedy_trust")),
        ("info term only",         dict(policy="greedy_info")),
        ("no cost term",           dict(policy="bacs", use_cost_term=False)),
        ("no ageing",              dict(policy="bacs_gated", use_ageing=False)),
        ("FIFO baseline",          dict(policy="fifo")),
        ("send-all (non-compliant)", dict(policy="send_all")),
    ]
    cfgs, names = [], []
    for name, kw in variants:
        c = SimConfig()
        for k, v in kw.items():
            setattr(c.scheduler, k, v)
        c.__dict__["_name"] = name
        cfgs.append(c)
        names.append(name)
    recs = _sweep(cfgs, seeds, label_fn=lambda c: dict(variant=c.__dict__.get("_name")))
    out = _agg(recs, "variant")
    order = {n: i for i, n in enumerate(names)}
    out["_o"] = out["variant"].map(order)
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)


# ------------------------------------------------------------------------ S6
def s6_scalability(seeds=range(3), counts=(2, 3, 4, 5), policies=("fifo", "bacs_gated"),
                   session_s=480.0):
    """Tests H3: per-robot airtime falls as 1/N, so the scheduling gap should widen."""
    recs = []
    for n in counts:
        for s in seeds:
            base = _mk(seed=s, n_robots=n)
            base.world.session_s = session_s
            pre = precompute(base)
            for p in policies:
                c = SimConfig()
                c.seed = s
                c.world.n_robots = n
                c.world.session_s = session_s
                c.scheduler.policy = p
                r = run(c, precomputed=pre)
                recs.append(dict(n_robots=n, policy=p, seed=s,
                                 pose_rmse=r.pose_rmse, align_rmse=r.align_rmse,
                                 trust_yield=r.trust_yield, n_delivered=r.n_delivered,
                                 sched_ms=r.sched_overhead_ms))
    return _agg(recs, ["n_robots", "policy"])


def wilcoxon(a, b):
    """Signed-rank test, matching the parent paper's statistical protocol."""
    from scipy.stats import wilcoxon as _w
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return dict(W=np.nan, p=np.nan, n=int(m.sum()))
    st = _w(a[m], b[m])
    return dict(W=float(st.statistic), p=float(st.pvalue), n=int(m.sum()))


# ------------------------------------------------------------------------ S7
def s7_surrogate_validation(seeds=range(3), counts=(2, 3, 4, 5),
                            policy="bacs_gated", session_s=480.0):
    """Validate the Eq. (12) surrogate against the exact information of Eq. (11).

    For each run we take the delivered constraints, recover the marginal
    covariance of every constrained relative pose from the converged graph
    Hessian, evaluate exact mutual information, and correlate it (Spearman rho)
    with the surrogate score the scheduler used. Reported per team size, because
    Section 6.5 conjectures that surrogate fidelity degrades as N grows and that
    this is why the scheduling advantage reverses.
    """
    recs = []
    for n in counts:
        for s in seeds:
            c = _mk(seed=s, n_robots=n)
            c.world.session_s = session_s
            c.scheduler.policy = policy
            pre = precompute(c)
            r = run(c, precomputed=pre, collect_graph=True)
            out = _surrogate_rho(r.extras)
            out.update(dict(n_robots=n, seed=s, n_delivered=r.n_delivered,
                            pose_rmse=r.pose_rmse))
            recs.append(out)
    return _agg(recs, "n_robots")


def _prior_covariance(truths, omega):
    """Covariance of the odometry-only graph: the prior a delivered inter-robot
    constraint is measured against. Node indexing matches the main graph, which
    adds all of robot 0's nodes, then robot 1's, and so on."""
    from .posegraph import PoseGraph
    from .world import relative
    g = PoseGraph()
    for t in truths:
        for k in range(len(t.odom)):
            g.add_node((t.rid, k), t.odom[k])
    for t in truths:
        for k in range(1, len(t.odom)):
            g.add_edge(g.idx((t.rid, k - 1)), g.idx((t.rid, k)),
                       relative(t.odom[k - 1], t.odom[k]), omega, 1.0)
    _, H = g.optimize(iterations=1)
    if H is None:
        return None
    Hd = H.toarray() if hasattr(H, "toarray") else np.asarray(H)
    try:
        return np.linalg.inv(Hd + 1e-9 * np.eye(Hd.shape[0]))
    except np.linalg.LinAlgError:
        return None


def _surrogate_rho(extras):
    """Spearman rho between surrogate info and exact information over delivered
    edges, computed two ways:

      rho_prior      -- exact info of each edge against the odometry-only prior
                        (the methodologically correct baseline: how much the edge
                        tightens the relative pose relative to dead reckoning);
      rho_posterior  -- against the fully converged graph covariance (retained
                        for comparison; this double-counts neighbouring edges and
                        is the wrong baseline).
    """
    graph = extras.get("graph")
    delivered = extras.get("delivered") or []
    omega = extras.get("omega")
    truths = extras.get("truths")
    out = dict(rho_prior=float("nan"), rho_posterior=float("nan"), n_pairs=0)
    if graph is None or not delivered:
        return out

    edges = []
    for c in delivered:
        i = graph.idx((c.rid_from, c.idx_from))
        j = graph.idx((c.rid_to, c.idx_to))
        if i is not None and j is not None:
            edges.append((c.info_hat, i, j))
    out["n_pairs"] = len(edges)
    if not edges:
        return out
    surro = [e[0] for e in edges]

    S_prior = _prior_covariance(truths, omega) if truths is not None else None
    if S_prior is not None:
        ex = [exact_info_from_cov(S_prior, i, j, omega) for _, i, j in edges]
        out["rho_prior"] = rank_correlation(surro, ex)

    H = extras.get("hessian")
    if H is not None:
        Hd = H.toarray() if hasattr(H, "toarray") else np.asarray(H)
        try:
            S_post = np.linalg.inv(Hd + 1e-9 * np.eye(Hd.shape[0]))
            ex = [exact_info_from_cov(S_post, i, j, omega) for _, i, j in edges]
            out["rho_posterior"] = rank_correlation(surro, ex)
        except np.linalg.LinAlgError:
            pass
    return out


# ---------------------------------------------------------------------- S7-C
def s7c_incremental_validation(seeds=range(3), counts=(2, 3, 4, 5),
                               policy="bacs_gated", session_s=240.0):
    """Incremental information-gain validation (the correct S7 for scheduling).

    For every candidate presented to the scheduler -- delivered or not, so the
    validation set is not biased by BACS's own choices -- compute the exact
    incremental information gain against the graph state *at the window the
    candidate was presented*:

        I_c = 1/2 log det( I + Omega_c J_c Sigma_ij,t J_c^T )

    where Sigma_ij,t is the joint marginal covariance of the two poses in the
    graph containing odometry plus everything delivered before window t, and J_c
    is the SE(2) relative-pose Jacobian at the current linearisation. Reports
    Spearman rho of this against the base surrogate (I_hat) and the
    observability-augmented surrogate (I_hat+), per team size.
    """
    recs = []
    for n in counts:
        for s in seeds:
            c = _mk(seed=s, n_robots=n)
            c.world.session_s = session_s
            c.scheduler.policy = policy
            pre = precompute(c)
            r = run(c, precomputed=pre, collect_graph=True)
            rho_base, rho_plus, npts = _s7c_rho(r.extras, c.infogain.w_obs)
            recs.append(dict(n_robots=n, seed=s, rho_base=rho_base,
                             rho_plus=rho_plus, n_candidates=npts,
                             pose_rmse=r.pose_rmse))
    return _agg(recs, "n_robots")


def s7c_paired(seeds=range(10), counts=(2, 3, 4, 5), policy="bacs_gated",
               session_s=240.0):
    """Per-seed S7-C with the paired observability test.

    Returns (summary, raw). `raw` has one row per (N, seed) with rho_base,
    rho_plus and their difference; `summary` aggregates per N and runs a
    one-sided Wilcoxon signed-rank test of H0: median(rho_plus - rho_base) = 0
    against H1: > 0. Reporting per-seed rho (rather than one pooled correlation)
    stops a single large candidate pool from dominating the statistic.
    """
    from scipy.stats import wilcoxon
    raw = []
    for n in counts:
        for s in seeds:
            c = _mk(seed=s, n_robots=n)
            c.world.session_s = session_s
            c.scheduler.policy = policy
            pre = precompute(c)
            r = run(c, precomputed=pre, collect_graph=True)
            rb, rp, npts = _s7c_rho(r.extras, c.infogain.w_obs)
            raw.append(dict(n_robots=n, seed=s, rho_base=rb, rho_plus=rp,
                            drho=rp - rb, n_candidates=npts))
    raw = pd.DataFrame(raw)
    rows = []
    for n in counts:
        d = raw[raw.n_robots == n]
        dr = d["drho"].values
        dr = dr[np.isfinite(dr)]
        if len(dr) >= 5 and not np.allclose(dr, 0):
            p = float(wilcoxon(dr, alternative="greater").pvalue)
        else:
            p = float("nan")
        rows.append(dict(
            n_robots=n,
            rho_base_mean=float(d.rho_base.mean()), rho_base_sd=float(d.rho_base.std()),
            rho_plus_mean=float(d.rho_plus.mean()), rho_plus_sd=float(d.rho_plus.std()),
            drho_mean=float(np.mean(dr)), drho_median=float(np.median(dr)),
            n_pos=int((dr > 0).sum()), n_seeds=int(len(dr)),
            wilcoxon_p_greater=p))
    return pd.DataFrame(rows), raw


def _s7c_rho(extras, w_obs):
    """Spearman rho(I_hat, I_exact) and rho(I_hat+, I_exact) over all candidates,
    using incremental gain against the graph state at each candidate's window."""
    from collections import defaultdict
    from .posegraph import PoseGraph, error_and_jacobians
    from .world import relative

    truths = extras.get("truths")
    om = extras.get("omega")
    scored = extras.get("scored") or []
    delivered = extras.get("delivered") or []
    if truths is None or not scored:
        return float("nan"), float("nan"), 0

    def build_prior():
        g = PoseGraph()
        for t in truths:
            for k in range(len(t.odom)):
                g.add_node((t.rid, k), t.odom[k])
        for t in truths:
            for k in range(1, len(t.odom)):
                g.add_edge(g.idx((t.rid, k - 1)), g.idx((t.rid, k)),
                           relative(t.odom[k - 1], t.odom[k]), om, 1.0)
        return g

    g = build_prior()
    d_by_win = defaultdict(list)
    for c in delivered:
        d_by_win[getattr(c, "_deliver_win", -1)].append(c)

    # Incrementally grow the graph window by window, caching (estimate, cov) at
    # each window that has candidates to score.
    wins = sorted({c._win for c in scored})
    cache, added_upto = {}, -1
    for w in wins:
        for ww in range(added_upto + 1, w):
            for c in d_by_win.get(ww, []):
                i = g.idx((c.rid_from, c.idx_from))
                j = g.idx((c.rid_to, c.idx_to))
                if i is not None and j is not None:
                    g.add_edge(i, j, c.z, om, max(getattr(c, "theta", 1.0), 1e-3))
        added_upto = w - 1
        X, H = g.optimize(iterations=1)
        if H is None:
            cache[w] = (None, None)
            continue
        Hd = H.toarray() if hasattr(H, "toarray") else np.asarray(H)
        try:
            Sig = np.linalg.inv(Hd + 1e-9 * np.eye(Hd.shape[0]))
        except np.linalg.LinAlgError:
            Sig = None
        cache[w] = (X.copy() if X is not None else None, Sig)

    Ihat, Iplus, Iexact = [], [], []
    for c in scored:
        X, Sig = cache.get(c._win, (None, None))
        if Sig is None or X is None:
            continue
        i = g.idx((c.rid_from, c.idx_from))
        j = g.idx((c.rid_to, c.idx_to))
        if i is None or j is None:
            continue
        _, A, B = error_and_jacobians(X[i], X[j], c.z)
        J = np.hstack([A, B])                      # 3x6 relative-pose Jacobian
        ix = [3 * i, 3 * i + 1, 3 * i + 2, 3 * j, 3 * j + 1, 3 * j + 2]
        Spair = Sig[np.ix_(ix, ix)]                # 6x6 joint marginal
        M = np.eye(3) + om @ (J @ Spair @ J.T)
        sign, logdet = np.linalg.slogdet(M)
        Iexact.append(0.5 * logdet if sign > 0 else 0.0)
        Ihat.append(c._info_base)
        Iplus.append(c._info_base + w_obs * c._obs)

    return (rank_correlation(Ihat, Iexact),
            rank_correlation(Iplus, Iexact), len(Iexact))


# ------------------------------------------------------------------------ S8
def s8_observability(seeds=range(5), counts=(2, 3, 4, 5), session_s=480.0):
    """Observability ablation across team size.

    Compares FIFO, plain gated BACS, and BACS+. The PRIMARY metric is
    map-alignment RMSE (`align_rmse`) -- the inter-robot map-fusion consistency
    the paper is about -- because the 30-seed study (`s8_30seed_raw.csv`,
    scripts/run_s8_30seed.py) shows per-step pose RMSE is odometry-drift-bound
    and carries no significant policy effect, whereas alignment separates the
    policies cleanly. `pose_rmse` is retained as a secondary column.
    """
    recs = []
    for n in counts:
        for s in seeds:
            base = _mk(seed=s, n_robots=n)
            base.world.session_s = session_s
            pre = precompute(base)
            for p in ("fifo", "bacs_gated", "bacs_plus"):
                c = SimConfig()
                c.seed = s
                c.world.n_robots = n
                c.world.session_s = session_s
                c.scheduler.policy = p
                # Use the corrected (deferral-derived) decay coefficient on every
                # arm so the observability comparison is not confounded by an
                # uncalibrated gamma.
                c.trust.gamma_rule = "deferral_derived"
                r = run(c, precomputed=pre)
                recs.append(dict(n_robots=n, policy=p, seed=s,
                                 align_rmse=r.align_rmse,   # PRIMARY metric
                                 pose_rmse=r.pose_rmse,     # secondary
                                 trust_yield=r.trust_yield,
                                 n_delivered=r.n_delivered))
    return _agg(recs, ["n_robots", "policy"])


# ------------------------------------------------------------------------ S9
def s9_deferral_gamma(seeds=range(5), policy="bacs_gated"):
    """Compare decay-coefficient rules, including the corrected deferral rules.

    Rows: fixed at the empirical optimum, the original drift derivation (Eq. 16)
    and its adaptive variant (both falsified in S4), and the two deferral-based
    rules that anchor gamma to the airtime-queueing timescale instead.
    """
    variants = [
        ("fixed 0.003",        dict(gamma_rule="fixed", gamma=0.003)),
        ("drift derived",      dict(gamma_rule="derived")),
        ("drift adaptive",     dict(gamma_rule="adaptive")),
        ("deferral derived",   dict(gamma_rule="deferral_derived")),
        ("deferral adaptive",  dict(gamma_rule="deferral_adaptive")),
    ]
    cfgs, names = [], []
    for name, kw in variants:
        c = SimConfig()
        c.scheduler.policy = policy
        for k, v in kw.items():
            setattr(c.trust, k, v)
        c.__dict__["_name"] = name
        cfgs.append(c)
        names.append(name)
    recs = _sweep(cfgs, seeds, label_fn=lambda c: dict(rule=c.__dict__.get("_name")))
    out = _agg(recs, "rule")
    order = {n: i for i, n in enumerate(names)}
    out["_o"] = out["rule"].map(order)
    out = out.sort_values("_o").drop(columns="_o").reset_index(drop=True)
    base = SimConfig()
    out.attrs["gamma_drift"] = gamma_derived(base.world, base.trust)
    out.attrs["gamma_deferral"] = gamma_deferral_derived(base.trust)
    return out


# --------------------------------------------------------------- EMRMF baseline
def emrmf_baseline() -> SimConfig:
    """The parent framework as-is: FIFO transmission, trust-weighted fusion, and
    the original drift-derived decay coefficient (Eq. 16). The reference point
    the BACS progression is measured against."""
    c = SimConfig()
    c.scheduler.policy = "fifo"
    c.trust.gamma_rule = "derived"
    return c


def progression(seeds=range(5)):
    """Research progression: EMRMF-original -> compliant FIFO -> BACS -> BACS+.

    Each stage changes exactly one thing so the contribution of each step is
    legible: the recalibrated (deferral) gamma, then the gated scheduler, then
    the observability term.
    """
    stages = []

    s0 = emrmf_baseline()
    s0.__dict__["_name"] = "EMRMF-original (FIFO, drift gamma)"
    stages.append(s0)

    s1 = SimConfig()
    s1.scheduler.policy = "fifo"
    s1.trust.gamma_rule = "deferral_derived"
    s1.__dict__["_name"] = "compliant FIFO (deferral gamma)"
    stages.append(s1)

    s2 = SimConfig()
    s2.scheduler.policy = "bacs_gated"
    s2.trust.gamma_rule = "deferral_derived"
    s2.__dict__["_name"] = "BACS (gated)"
    stages.append(s2)

    s3 = SimConfig()
    s3.scheduler.policy = "bacs_plus"
    s3.trust.gamma_rule = "deferral_derived"
    s3.__dict__["_name"] = "BACS+ (observability)"
    stages.append(s3)

    recs = _sweep(stages, seeds, label_fn=lambda c: dict(stage=c.__dict__.get("_name")))
    out = _agg(recs, "stage")
    order = {c.__dict__["_name"]: i for i, c in enumerate(stages)}
    out["_o"] = out["stage"].map(order)
    return out.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def summary_stats(values) -> dict:
    """Mean, std, median and a normal-approximation 95% CI for one metric.

    Reported alongside the Wilcoxon test for the principal comparisons so the
    headline percentages carry dispersion and interval estimates, not point
    values alone.
    """
    a = np.asarray([v for v in values if np.isfinite(v)], float)
    n = len(a)
    if n == 0:
        return dict(n=0, mean=np.nan, std=np.nan, median=np.nan,
                    ci_lo=np.nan, ci_hi=np.nan)
    mean = float(a.mean())
    std = float(a.std(ddof=1)) if n > 1 else 0.0
    half = 1.96 * std / np.sqrt(n) if n > 1 else 0.0
    return dict(n=n, mean=mean, std=std, median=float(np.median(a)),
                ci_lo=mean - half, ci_hi=mean + half)


def cliffs_delta(a, b) -> float:
    """Cliff's delta effect size for two independent samples, in [-1, 1].

    A nonparametric complement to the Wilcoxon p-value: the probability that a
    draw from `a` exceeds a draw from `b`, minus the reverse.
    """
    a = np.asarray([v for v in a if np.isfinite(v)], float)
    b = np.asarray([v for v in b if np.isfinite(v)], float)
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    gt = (a[:, None] > b[None, :]).sum()
    lt = (a[:, None] < b[None, :]).sum()
    return float((gt - lt) / (len(a) * len(b)))
