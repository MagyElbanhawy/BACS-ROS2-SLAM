# EMRMF/BACS+ bridge runbook

This runbook is intentionally executable by the researcher, not by the
preparation agent. No experiment, test, analysis, or plotting command was run
while preparing this change. Existing results remain untouched.

## Implementation summary

`emrmf_reference` is an explicit scheduler policy that uses the current
simulator's airtime budget but admits candidates in oldest-first order. It uses
the current server trust and current weighted SE(2) pose graph, with
`gamma_rule="derived"` to represent the original drift-calibrated temporal
decay. Frozen BACS+ uses `bacs_plus`, `w_obs=0.30`, `obs_ref=6.0`, and
`gamma_rule="deferral_derived"`. Both arms receive the same `precompute()` data.

Shared: world, trajectories, odometry, candidate timestamps, measurement noise,
outliers, payloads, LoRa configuration, channel model, optimizer, pose graph,
and metrics. Differing: trust decay rule and candidate ordering/information
signal. Because each arm has a distinct selection path, exact per-packet channel
draw reuse is not possible without changing the channel API; the same seed and
configuration are used, and this limitation is recorded in the crosswalk.

## STAGE A - environment/checks

Run from the repository root:

```powershell
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -c "import numpy, pandas, scipy, matplotlib; print('dependencies ok')"
git diff --check
git status --short
```

These check the interpreter, required packages, whitespace, and changed-file
scope. Expected runtime: under 10 seconds. Expected output: Python version,
`dependencies ok`, no `git diff --check` errors, and only intended bridge files.
Send back the complete output if any command fails.

## STAGE B - unit tests

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_emrmf_bridge.py tests/test_scheduler.py tests/test_fusion_core.py
```

This checks the new policy, FIFO ordering, airtime budget, trust equation, and
pose-graph fusion. Expected runtime: seconds to a minute. Expected output: all
selected tests pass. Send back the complete pytest output, including failures.

## STAGE C - very small smoke test

```powershell
.\venv\Scripts\python.exe scripts\revision\run_emrmf_bacs_bridge.py --quick
```

This executes one seed, two robots, C0, and a 60-second session for both arms.
Expected runtime: typically seconds to a few minutes depending on the machine.
Expected files: `raw.csv`, `primary.csv`, `by_condition.csv`,
`by_robot_count.csv`, `mechanism.csv`, and `runtime.txt` under
`paper_results\revision\emrmf_bacs_bridge\`. Send back the terminal output and
the headers plus row counts of those CSVs; do not edit values manually.

## STAGE D - verification of smoke-test outputs

```powershell
.\venv\Scripts\python.exe -c "import pandas as pd; from pathlib import Path; p=Path('paper_results/revision/emrmf_bacs_bridge'); [print(f.name, len(pd.read_csv(f)), list(pd.read_csv(f).columns)) for f in sorted(p.glob('*.csv'))]"
git diff --stat
git status --short
```

This verifies that the smoke run produced non-empty, schema-bearing outputs and
did not modify unrelated files. Expected runtime: under 10 seconds. Send back
the complete output and any unexpected path or column.

## STAGE E - full preregistered EMRMF-vs-BACS+ experiment

After reviewing the smoke output and approving the protocol:

```powershell
.\venv\Scripts\python.exe scripts\revision\run_emrmf_bacs_bridge.py --full
```

This runs 30 seeds x 4 robot counts x 4 conditions x 2 arms = 960 simulated
arm runs (480 paired cases). Expected runtime: machine-dependent; budget tens of
minutes to several hours. Expected files: the bridge CSVs listed above plus
`runtime.txt`, with 960 rows in `raw.csv`. Send back the terminal output,
`runtime.txt`, CSV row counts, and a copy of `primary.csv`.

## STAGE F - statistical analysis

```powershell
.\venv\Scripts\python.exe scripts\revision\analyze_emrmf_bacs_bridge.py
```

This recomputes paired primary statistics from `raw.csv` without rerunning the
simulation. Expected runtime: seconds. Expected output: refreshed `primary.csv`.
Send back the complete output and the resulting CSV.

## STAGE G - figures and paper tables

```powershell
.\venv\Scripts\python.exe scripts\revision\plot_emrmf_bacs_bridge.py
```

This creates a figure from completed summary data only. Expected runtime:
seconds. Expected output: `fig_emrmf_vs_bacs_scalability.png`. Send back the
image and the summary CSVs before any paper claim is drafted.

No publication claim should be written until the real outputs have been checked
for paired keys, missing values, unchanged conditions, and honest favorable or
unfavorable outcomes.
