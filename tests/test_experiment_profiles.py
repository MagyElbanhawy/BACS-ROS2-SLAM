from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_hardware_rerun_profiles_capture_fused_pose_logging_and_budget() -> None:
    config = yaml.safe_load((ROOT / "config" / "hardware_experiment_profiles.yaml").read_text(encoding="utf-8"))
    profile = config["hardware_rerun"]
    assert "/fused_poses" in profile["bag_topics"]
    assert profile["scheduler"]["default"]["trust_threshold"] == 0.05
    assert profile["scheduler"]["default"]["ranking"] == "information_density"
    assert profile["airtime_budget"]["target_airtime_s_per_min"] == 60.0 * profile["scheduler"]["default"]["duty_cycle"]


def test_surplus_candidate_profile_and_interleaved_rotation_are_explicit() -> None:
    config = yaml.safe_load((ROOT / "config" / "hardware_experiment_profiles.yaml").read_text(encoding="utf-8"))
    rerun = config["hardware_rerun"]
    surplus = rerun["candidate_generation"]["surplus_candidates"]
    assert surplus["target_candidates_per_10_min"] >= 60
    assert surplus["keyframe_period_s"] < rerun["candidate_generation"]["default"]["keyframe_period_s"]
    assert rerun["interleaved_protocol"]["segment_minutes"] == 12
    assert rerun["interleaved_protocol"]["rotations"] == [
        ["FIFO", "BACS", "BACS+"],
        ["BACS", "BACS+", "FIFO"],
        ["BACS+", "FIFO", "BACS"],
    ]
