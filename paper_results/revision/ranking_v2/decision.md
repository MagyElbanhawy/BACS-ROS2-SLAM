# Ranking v2: DEV decision

Written 2026-09-26 01:09:29 from `dev_raw.csv` (sha256 `793372a83ee0665d78ceb4e78b75981831d8b5bd6715d193395fa88cfd930e7c`), before any TEST seed was simulated.

## Rule (fixed before DEV was run)

1. Metric: DEV mean `align_rmse` pooled over all 40 seed-team pairs (seeds 0-9 x N = 2-5), nominal channel.
2. Selectable: TW (`plus_tw`), TW-Arrival (`plus_tw_arr`), TW-Arrival-Sub (`plus_tw_arr_sub`). `bacs_tw` (TW without the observability term) is an ablation row only.
3. Exactly one candidate is frozen: the lowest pooled DEV mean (ties broken by arm name). No threshold against the existing arms is applied.
4. TEST (seeds 40-69) runs all controls and every ablation row under the four communication conditions fixed in the script before DEV: `nominal` (defaults), `loss_iid_0.2` {'loss_model': 'independent', 'loss_rate': 0.2}, `burst_ge` {'loss_model': 'burst'}, `delay_30s` {'extra_delay_s': 30.0}.
5. Confirmatory family: the frozen candidate on the nominal condition. Stress conditions and other rows are reported with their own Holm families.

## DEV pooled means (40 pairs, nominal)

| arm | label | align_rmse (m) | pose_rmse (m) | trust_yield | n_delivered | age at arrival (s) | retention | pair diversity |
|---|---|---|---|---|---|---|---|---|
| `bacs_gated` | BACS | 0.2172 | 0.3894 | 0.4211 | 32.0 | 105.5 | 0.524 | 1.000 |
| `plus_0.30_6` | BACS+ (0.30, 6) | 0.2205 | 0.3954 | 0.4164 | 32.0 | 107.5 | 0.520 | 1.000 |
| `plus_tw` | TW | 0.2566 | 0.3779 | 0.4938 | 32.0 | 108.1 | 0.604 | 1.000 |
| `plus_tw_arr` | TW-Arrival | 0.2665 | 0.3877 | 0.5189 | 32.0 | 96.2 | 0.626 | 1.000 |
| `random` | Random | 0.2680 | 0.4103 | 0.4962 | 32.0 | 81.0 | 0.589 | 1.000 |
| `plus_tw_arr_sub` | TW-Arrival-Sub | 0.2693 | 0.4111 | 0.5125 | 32.0 | 96.5 | 0.618 | 1.000 |
| `fifo` | FIFO | 0.2796 | 0.3681 | 0.4462 | 32.0 | 125.7 | 0.559 | 1.000 |
| `bacs_tw` | TW on I (no obs.) | 0.2855 | 0.4069 | 0.4914 | 32.0 | 104.5 | 0.597 | 1.000 |

## DEV means by N (align_rmse, m)

| arm | N=2 | N=3 | N=4 | N=5 |
|---|---|---|---|---|
| `fifo` | 0.3214 | 0.3336 | 0.2540 | 0.2095 |
| `random` | 0.1876 | 0.2162 | 0.2133 | 0.4547 |
| `bacs_gated` | 0.2028 | 0.2817 | 0.2042 | 0.1799 |
| `plus_0.30_6` | 0.2010 | 0.2704 | 0.1971 | 0.2133 |
| `bacs_tw` | 0.1909 | 0.3480 | 0.2556 | 0.3477 |
| `plus_tw` | 0.1824 | 0.2787 | 0.2225 | 0.3430 |
| `plus_tw_arr` | 0.1743 | 0.2912 | 0.2344 | 0.3660 |
| `plus_tw_arr_sub` | 0.1857 | 0.2912 | 0.2344 | 0.3660 |

## Decision

CHOSEN: plus_tw

`plus_tw` (TW): DEV mean 0.2566 m, +16.4 % vs plus_0.30_6, -4.2 % vs random.
