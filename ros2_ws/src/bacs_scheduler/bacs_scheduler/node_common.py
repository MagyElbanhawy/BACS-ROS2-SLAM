"""Shared helpers for the hardware nodes: output folders, clock snapshots, radio setup."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .rylr998 import Rylr998Link, configuration_commands


def run_dir(log_dir: str, session: str, run: int) -> Path:
    path = Path(log_dir).expanduser() / session / f"run_{run:02d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clock_snapshot(path: Path) -> None:
    """Record system time and chrony state so cross-machine timestamps can be checked later."""
    try:
        tracking = subprocess.run(["chronyc", "tracking"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError) as error:
        tracking = f"UNAVAILABLE: {error}"
    path.write_text(f"time_ns={time.time_ns()}\n{tracking}", encoding="utf-8")


def configure_radio(link: Rylr998Link, path: Path, address: int, network_id: int, bw_code: int,
                    preamble: int, power_dbm: int) -> None:
    """Configure the module and store every command with the module's own reply."""
    replies = link.configure(configuration_commands(address, network_id, bw_code=bw_code,
                                                    preamble=preamble, power_dbm=power_dbm))
    path.write_text(json.dumps([{"command": c, "response": r} for c, r in replies], indent=2), encoding="utf-8")
    failed = [c for c, r in replies if r in ("TIMEOUT",) or r.startswith("+ERR")]
    if failed:
        raise RuntimeError(f"RYLR998 rejected {failed}; see {path}")
