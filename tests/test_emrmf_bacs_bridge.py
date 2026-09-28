"""
Unit & Integration Tests for EMRMF vs BACS+ Controlled Bridge Experiment.

Verify policy registration, configuration integrity, precompute determinism,
shared world input handling, and RunResult metric completeness.

NOTE: DO NOT RUN THIS FILE AUTOMATICALLY.
Execute manually: python -m pytest tests/test_emrmf_bacs_bridge.py
"""
import pytest
import numpy as np

from bacs_sim.config import SimConfig
from bacs_sim.schedulers import POLICIES, schedule
from bacs_sim.simulator import run, precompute
from bacs_sim.experiments import emrmf_reference_arm, bacs_plus_frozen_arm
from bacs_sim.lora import airtime_budget


def test_emrmf_reference_policy_registered():
    """Verify emrmf_reference policy is registered in POLICIES."""
    assert "emrmf_reference" in POLICIES


def test_emrmf_reference_arm_config():
    """Verify emrmf_reference_arm helper builds correct SimConfig."""
    cfg = emrmf_reference_arm()
    assert cfg.scheduler.policy == "emrmf_reference"
    assert cfg.trust.gamma_rule == "derived"
    assert cfg.scheduler.use_observability is False
    assert cfg.scheduler.trust_gate == 0.0


def test_bacs_plus_frozen_arm_config():
    """Verify bacs_plus_frozen_arm helper builds correct SimConfig."""
    cfg = bacs_plus_frozen_arm()
    assert cfg.scheduler.policy == "bacs_plus"
    assert cfg.trust.gamma_rule == "deferral_derived"
    assert cfg.infogain.w_obs == 0.30
    assert cfg.infogain.obs_ref == 6.0
    assert cfg.scheduler.use_observability is True
    assert cfg.scheduler.trust_gate == 0.05


def test_precompute_determinism():
    """Verify precompute produces identical world & candidate realization for fixed seed."""
    cfg = SimConfig(seed=77)
    cfg.world.session_s = 120.0

    truths1, cands1 = precompute(cfg)
    truths2, cands2 = precompute(cfg)

    assert len(truths1) == len(truths2)
    for t1, t2 in zip(truths1, truths2):
        assert np.allclose(t1.gt, t2.gt)
        assert np.allclose(t1.odom, t2.odom)

    for rid in cands1:
        assert len(cands1[rid]) == len(cands2[rid])
        for c1, c2 in zip(cands1[rid], cands2[rid]):
            assert c1.t_created == c2.t_created
            assert c1.is_outlier == c2.is_outlier
            assert np.allclose(c1.z, c2.z)


def test_shared_precompute_between_arms():
    """Verify running both emrmf_reference and bacs_plus on shared precomputed data."""
    base_cfg = SimConfig(seed=80)
    base_cfg.world.session_s = 120.0
    base_cfg.world.n_robots = 2

    pre = precompute(base_cfg)

    # Arm 1: EMRMF reference
    cfg_e = emrmf_reference_arm()
    cfg_e.seed = 80
    cfg_e.world.session_s = 120.0
    cfg_e.world.n_robots = 2
    res_e = run(cfg_e, precomputed=pre)

    # Arm 2: BACS+
    cfg_b = bacs_plus_frozen_arm()
    cfg_b.seed = 80
    cfg_b.world.session_s = 120.0
    cfg_b.world.n_robots = 2
    res_b = run(cfg_b, precomputed=pre)

    assert np.isfinite(res_e.align_rmse)
    assert np.isfinite(res_b.align_rmse)
    assert np.isfinite(res_e.pose_rmse)
    assert np.isfinite(res_b.pose_rmse)


def test_scheduler_fifo_order():
    """Verify emrmf_reference policy schedules candidates in FIFO arrival order."""
    cfg = SimConfig()
    cfg.scheduler.policy = "emrmf_reference"

    base_cfg = SimConfig(seed=42)
    base_cfg.world.session_s = 120.0
    _, cands_dict = precompute(base_cfg)
    cands = cands_dict[0][:5]

    budget = airtime_budget(cfg.scheduler.window_s, cfg.lora, cfg.world.n_robots)
    rng = np.random.default_rng(42)

    scheduled = schedule(cands, budget, cfg.scheduler, cfg.lora, rng)
    if len(scheduled) > 1:
        # Should be sorted by t_created ascending (oldest first)
        t_created_list = [c.t_created for c in scheduled]
        assert t_created_list == sorted(t_created_list)


def test_run_result_extra_metrics():
    """Verify RunResult extras contain mechanism profiling metrics."""
    cfg = SimConfig(seed=90)
    cfg.world.session_s = 120.0
    res = run(cfg)

    assert "n_accepted" in res.extras
    assert "n_rejected" in res.extras
    assert "n_outliers_delivered" in res.extras
    assert "n_outliers_rejected" in res.extras
    assert "n_inliers_rejected" in res.extras
