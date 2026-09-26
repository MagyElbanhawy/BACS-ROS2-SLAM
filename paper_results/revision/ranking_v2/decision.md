# Ranking v2: DEV decision

Written by `ranking_v2.py dev` on 2026-09-26 09:31:40 UTC, before any TEST run.
Rule (fixed in advance): among tw_now, tw_arrival and tw_arrival_sub, choose the lowest mean
map-alignment RMSE over DEV seeds 0-9 x N = 2, 3, 4, 5 (40 seed-team pairs), condition C0.

**Chosen variant: `tw_now`** (primary hypothesis for TEST: tw_now vs random).

DEV ablation table (map-alignment RMSE, m; mean per N, pooled mean and SD over 40 pairs):

| policy | N=2 | N=3 | N=4 | N=5 | pooled mean | pooled SD |
|---|---|---|---|---|---|---|
| fifo | 0.3214 | 0.3336 | 0.2540 | 0.2095 | 0.2796 | 0.1286 |
| random | 0.1876 | 0.2162 | 0.2133 | 0.4547 | 0.2680 | 0.2210 |
| info_only | 0.2028 | 0.2897 | 0.2030 | 0.2052 | 0.2252 | 0.0953 |
| bacs_gated | 0.2028 | 0.2817 | 0.2042 | 0.1799 | 0.2172 | 0.0922 |
| plus_0.30_6 | 0.2010 | 0.2704 | 0.1971 | 0.2133 | 0.2205 | 0.1170 |
| tw_now **(chosen)** | 0.2045 | 0.2583 | 0.2256 | 0.2822 | 0.2427 | 0.1268 |
| tw_arrival | 0.2097 | 0.2633 | 0.2624 | 0.3217 | 0.2643 | 0.1550 |
| tw_arrival_sub | 0.2053 | 0.2633 | 0.2624 | 0.3217 | 0.2632 | 0.1547 |

This file is not modified after it is written.
