"""
Simulation loop.

Executes a full mapping session: robots generate candidates, the scheduler
admits a subset within the duty-cycle budget, the channel delivers or drops
them, the server assigns trust by Eq. (7) and solves the weighted pose graph.
"""
import time
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List

from .config import SimConfig
from .world import build_world, generate_candidates, relative, wrap
from .lora import Channel, time_on_air, airtime_budget
from .trust import GammaController, predicted_delay, predicted_trust, server_trust
from .infogain import CoverageMap, surrogate_info
from .observability import PairObservability
from .schedulers import schedule, compute_utility
from .posegraph import PoseGraph
from .agents import make_agent


@dataclass
class RunResult:
    policy: str
    pose_rmse: float = float("nan")        # per-step position RMSE vs ground truth
    align_rmse: float = float("nan")       # inter-robot frame alignment error
    trust_yield: float = float("nan")      # mean theta over received constraints
    accept_rate: float = float("nan")      # fraction with theta > threshold
    airtime_util: float = float("nan")
    n_candidates: int = 0
    n_sent: int = 0
    n_delivered: int = 0
    bytes_sent: int = 0
    efficiency: float = float("nan")       # RMSE reduction per kB vs no-comms
    sched_overhead_ms: float = float("nan")
    starvation: int = 0
    outlier_share: float = float("nan")    # fraction of delivered that are outliers
    gamma_final: float = float("nan")
    dt_pred_bias: float = float("nan")     # mean(dt_hat - dt_actual)
    extras: dict = field(default_factory=dict)


def _odometry_information(cfg):
    return np.diag([1.0 / max(cfg.meas_sigma_xy ** 2, 1e-9),
                    1.0 / max(cfg.meas_sigma_xy ** 2, 1e-9),
                    1.0 / max(cfg.meas_sigma_theta ** 2, 1e-9)])


def run(cfg: SimConfig, precomputed=None, collect_graph: bool = False) -> RunResult:
    rng = np.random.default_rng(cfg.seed)
    w = cfg.world
    # BACS+ observability term is active for the bacs_plus policy or when
    # explicitly switched on for an ablation.
    use_obs = (cfg.scheduler.use_observability
               or cfg.scheduler.policy == "bacs_plus")
    pair_obs = PairObservability(cfg.infogain.obs_ref)

    if precomputed is None:
        truths = build_world(w, rng)
        cands = generate_candidates(truths, w, rng)
    else:
        truths, cands = precomputed
        cands = {k: [_clone(c) for c in v] for k, v in cands.items()}

    agents = {r: make_agent(r, cfg.agent(r), rng) for r in range(w.n_robots)}
    for rid, lst in cands.items():
        for c in lst:
            agents[rid].on_report(c)

    gamma_ctl = GammaController(cfg.trust, w)
    channel = Channel(cfg.channel, cfg.lora, rng)
    coverage = {r: CoverageMap(cfg.infogain) for r in range(w.n_robots)}

    budget_per_window = airtime_budget(cfg.scheduler.window_s, cfg.lora, w.n_robots)
    n_windows = int(np.ceil(w.session_s / cfg.scheduler.window_s))

    pending: Dict[int, List] = {r: [] for r in range(w.n_robots)}
    queues: Dict[int, int] = {r: 0 for r in range(w.n_robots)}
    delivered: List = []
    airtime_used = 0.0
    airtime_avail = 0.0
    bytes_sent = 0
    n_sent = 0
    sched_time = 0.0
    max_deferral = 0
    dt_errors = []

    # Local node degree, used by the information surrogate.
    degree = {r: np.zeros(len(truths[r].gt), int) for r in range(w.n_robots)}
    last_map_time = 0.0

    # Server-side graph, built incrementally so that the fused map can be fed
    # back to the robots.  This feedback is what makes Eq. (8) work: the
    # provisional residual must be computed against corrected poses, not raw
    # odometry, or it is dominated by the transmitter's own accumulated drift.
    om = _odometry_information(w)
    graph = PoseGraph()
    for rid in range(w.n_robots):
        odo = truths[rid].odom
        for k in range(len(odo)):
            graph.add_node((rid, k), odo[k])
        for k in range(1, len(odo)):
            graph.add_edge(graph.idx((rid, k - 1)), graph.idx((rid, k)),
                           relative(odo[k - 1], odo[k]), om, 1.0)
    # Corrected pose belief published to robots; starts at odometry.
    fused = {rid: truths[rid].odom.copy() for rid in range(w.n_robots)}

    for wi in range(n_windows):
        t0 = wi * cfg.scheduler.window_s
        t1 = t0 + cfg.scheduler.window_s
        gamma = gamma_ctl.update()

        for rid in range(w.n_robots):
            fresh = [c for c in cands[rid] if t0 <= c.t_created < t1]
            pending[rid].extend(fresh)
            if not pending[rid]:
                continue

            map_age = t1 - last_map_time
            # Two-pass prediction: queue position is not known until candidates
            # are ranked, and ranking depends on predicted delay.  Pass 1 uses
            # the mid-window expectation, pass 2 uses the resulting order.
            for _pass in (0, 1):
                if _pass == 0:
                    order = pending[rid]
                    queue_of = {id(c): budget_per_window * 0.5 for c in order}
                else:
                    order = sorted(pending[rid], key=lambda c: c.utility, reverse=True)
                    queue_of, acc = {}, 0.0
                    for c in order:
                        queue_of[id(c)] = acc
                        acc += time_on_air(c.payload_bytes, cfg.lora)
                _score_batch(order, queue_of, cfg, gamma, gamma_ctl, truths,
                             coverage[rid], degree[rid], agents[rid], rid,
                             map_age, w, fused, pair_obs, use_obs,
                             log_window=(wi if collect_graph else None))
            if cfg.scheduler.expire_below_trust:
                pending[rid] = [c for c in pending[rid]
                                if c.theta_hat >= cfg.trust.floor * 1.5]

            ts = time.perf_counter()
            chosen = schedule(pending[rid], budget_per_window,
                              cfg.scheduler, cfg.lora, rng)
            sched_time += time.perf_counter() - ts

            airtime_avail += budget_per_window
            chosen_ids = set(id(c) for c in chosen)

            t_cursor = t0
            for c in chosen:
                c.t_sent = max(t_cursor, c.t_created)
                ok, t_recv, used, attempts = channel.transmit(c.payload_bytes, c.t_sent)
                t_cursor = t_recv if ok else t_cursor + used
                airtime_used += used
                bytes_sent += c.payload_bytes * attempts
                n_sent += 1
                c.attempts = attempts
                c.delivered = ok
                c.t_recv = t_recv
                dt_actual = t_recv - c.t_created
                gamma_ctl.observe(dt_actual, not ok)
                if ok:
                    dt_errors.append(c.dt_hat - dt_actual)
                    delivered.append(c)
                    coverage[rid].mark(truths[rid].odom[c.idx_from][:2])
                    degree[rid][c.idx_from] += 1
                    pair_obs.mark(c.rid_from, c.rid_to)
                    if collect_graph:
                        c._deliver_win = wi

            rest = []
            for c in pending[rid]:
                if id(c) in chosen_ids:
                    continue
                c.deferrals += 1
                max_deferral = max(max_deferral, c.deferrals)
                if c.deferrals < 12:
                    rest.append(c)
            pending[rid] = rest

        # ---- server: ingest this window's arrivals, re-optimise, republish ----
        new_edges = [c for c in delivered if not getattr(c, "_ingested", False)]
        for c in new_edges:
            c._ingested = True
            dt = c.t_recv - c.t_created
            pred = relative(fused[c.rid_from][c.idx_from], fused[c.rid_to][c.idx_to])
            c.theta = server_trust(float(np.linalg.norm((c.z - pred)[:2])),
                                   dt, cfg.trust, gamma_ctl.value)
            graph.add_edge(graph.idx((c.rid_from, c.idx_from)),
                           graph.idx((c.rid_to, c.idx_to)), c.z, om, c.theta)

        if new_edges and (wi % max(w.fusion_every_windows, 1) == 0):
            Xk, _ = graph.optimize(iterations=6)
            for rid in range(w.n_robots):
                fused[rid] = np.array([Xk[graph.idx((rid, k))]
                                       for k in range(len(truths[rid].gt))])
            last_map_time = t1

    # ---------------------------------------------- final global optimisation
    thetas = [c.theta for c in delivered]
    X, H_final = graph.optimize()

    # ------------------------------------------------------------- evaluation
    errs = []
    for rid in range(w.n_robots):
        gt = truths[rid].gt
        est = np.array([X[graph.idx((rid, k))] for k in range(len(gt))])
        # Anchor each robot's estimate to its own start pose: we score internal
        # consistency of the trajectory, not the arbitrary global gauge.
        est_a = _align_first(est, gt)
        errs.append(np.linalg.norm(est_a[:, :2] - gt[:, :2], axis=1))
    pose_rmse = float(np.sqrt(np.mean(np.concatenate(errs) ** 2)))

    # Map alignment: discrepancy between the two robots' estimates of the same
    # place.  Evaluated on ground-truth co-location pairs in the overlap region,
    # so a policy that delivers nothing scores badly rather than well - each
    # robot then drifts independently and their maps disagree.
    align = []
    for a in range(w.n_robots):
        for b in range(a + 1, w.n_robots):
            Pa, Pb = truths[a].gt[:, :2], truths[b].gt[:, :2]
            stride = max(len(Pb) // 200, 1)
            jb = np.arange(0, len(Pb), stride)
            d = np.linalg.norm(Pa[:, None, :] - Pb[None, jb, :], axis=2)
            ii, jj = np.where(d < w.obs_radius)
            if len(ii) == 0:
                continue
            sel = np.linspace(0, len(ii) - 1, min(len(ii), 400)).astype(int)
            for k in sel:
                ka, kb = int(ii[k]), int(jb[jj[k]])
                ev = X[graph.idx((a, ka))][:2] - X[graph.idx((b, kb))][:2]
                gv = truths[a].gt[ka, :2] - truths[b].gt[kb, :2]
                align.append(np.linalg.norm(ev - gv))
    align_rmse = float(np.sqrt(np.mean(np.square(align)))) if align else float("nan")

    n_cand = sum(len(v) for v in cands.values())
    res = RunResult(
        policy=cfg.scheduler.policy,
        pose_rmse=pose_rmse,
        align_rmse=align_rmse,
        trust_yield=float(np.mean(thetas)) if thetas else 0.0,
        accept_rate=float(np.mean([t > cfg.trust.accept_threshold for t in thetas])) if thetas else 0.0,
        airtime_util=float(airtime_used / airtime_avail) if airtime_avail > 0 else 0.0,
        n_candidates=n_cand,
        n_sent=n_sent,
        n_delivered=len(delivered),
        bytes_sent=bytes_sent,
        sched_overhead_ms=float(1000.0 * sched_time / max(n_windows, 1)),
        starvation=int(max_deferral),
        outlier_share=float(np.mean([c.is_outlier for c in delivered])) if delivered else 0.0,
        gamma_final=float(gamma_ctl.value),
        dt_pred_bias=float(np.mean(dt_errors)) if dt_errors else float("nan"),
    )
    if collect_graph:
        # Exposed for the S7 surrogate-validation experiment, which needs the
        # converged graph, its Hessian, and the delivered constraints to compute
        # exact mutual information post hoc.
        res.extras["graph"] = graph
        res.extras["hessian"] = H_final
        res.extras["delivered"] = delivered
        res.extras["omega"] = om
        res.extras["truths"] = truths
        # Every candidate presented to the scheduler (delivered or not), tagged
        # at first scoring with its window and surrogate values. Used by the
        # incremental S7-C validation, which must score all candidates to avoid
        # the selection bias of validating only on what BACS chose to deliver.
        res.extras["scored"] = [c for lst in cands.values() for c in lst
                                if hasattr(c, "_win")]
    return res


def _align_first(est, gt):
    """Express est in a frame whose first pose coincides with the ground truth."""
    out = est.copy()
    dth = wrap(gt[0, 2] - est[0, 2])
    c, s = np.cos(dth), np.sin(dth)
    R = np.array([[c, -s], [s, c]])
    out[:, :2] = (R @ (est[:, :2] - est[0, :2]).T).T + gt[0, :2]
    out[:, 2] = wrap(est[:, 2] + dth)
    return out


def _clone(c):
    import copy
    d = copy.copy(c)
    d.z = c.z.copy()
    d.deferrals = 0
    d.delivered = False
    d.theta = 0.0
    d.theta_hat = 0.0
    d.info_hat = 0.0
    d.tampered = False
    return d


def precompute(cfg: SimConfig):
    """Build world and candidates once so policies are compared on identical data."""
    rng = np.random.default_rng(cfg.seed)
    truths = build_world(cfg.world, rng)
    cands = generate_candidates(truths, cfg.world, rng)
    return truths, cands


def _score_batch(cands, queue_of, cfg, gamma, gamma_ctl, truths, cov, degree,
                 agent, rid, map_age, w, fused, pair_obs=None, use_obs=False,
                 log_window=None):
    """Populate theta_hat, info_hat and utility for one window's candidates."""
    for c in cands:
        # Expected further deferral: with an oversupply ratio R, a candidate
        # ranked at position r among n contenders for k slots waits about r/k
        # windows.  Estimated here from the observed backlog.
        defer = queue_of[id(c)] / max(cfg.scheduler.window_s * cfg.lora.duty_cycle, 1e-9)
        c.dt_hat = predicted_delay(c.payload_bytes, queue_of[id(c)], cfg.lora,
                                   gamma_ctl.p_loss, deferral_windows=defer,
                                   window_s=cfg.scheduler.window_s)
        pred = relative(fused[rid][c.idx_from], fused[c.rid_to][c.idx_to])
        res = float(np.linalg.norm((c.z - pred)[:2]))
        th = predicted_trust(res, c.dt_hat, cfg.trust, gamma,
                             map_age=map_age, v_max=w.speed)
        nov = cov.novelty(truths[rid].odom[c.idx_from][:2])
        deg = int(degree[c.idx_from])
        loop = abs(truths[rid].t[c.idx_from] - truths[c.rid_to].t[c.idx_to])
        obs = pair_obs.score(c.rid_from, c.rid_to) if (use_obs and pair_obs) else 0.0
        base_ig = surrogate_info(nov, deg, loop, cfg.infogain, observability=0.0)
        ig = base_ig + cfg.infogain.w_obs * obs if use_obs else base_ig
        th, ig = agent.on_declare(th, ig)
        c.theta_hat, c.info_hat = th, ig
        c.utility = compute_utility(c, cfg.scheduler, cfg.lora)
        if log_window is not None and not hasattr(c, "_win"):
            # First time this candidate is scored: snapshot for S7-C. `_obs` is
            # the observability score at presentation; I_hat = base, I_hat+ =
            # base + w_obs*obs.
            c._win = int(log_window)
            c._info_base = float(base_ig)
            c._obs = float(obs if use_obs else pair_obs.score(c.rid_from, c.rid_to)
                           if pair_obs else 0.0)
