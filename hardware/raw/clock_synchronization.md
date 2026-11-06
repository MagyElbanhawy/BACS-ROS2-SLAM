# Clock Synchronization Status

**Historical Runs (HWS-002, HWS-003, HWS-005):**
Strict NTP/Chrony synchronization logs were not preserved for these original historical sessions. Therefore, absolute one-way channel delay ($T_{\mathrm{channel}} = t_{\mathrm{RX}} - t_{\mathrm{TX}}$) across different robots cannot be strictly guaranteed due to unknown inter-robot clock offsets.

**How Timing Metrics Remain Valid:**
1. **Scheduling Deferral ($T_{\mathrm{deferral}}$):** This is the primary physical metric evaluated in the manuscript. It is calculated entirely on the **local clock** of the transmitting robot ($t_{\mathrm{TX}} - t_{\mathrm{generation}}$) and is 100% immune to inter-robot clock drift.
2. **Channel Latency:** For historical runs, we rely on application-layer Round-Trip Time (RTT) observations or relative timing rather than strict one-way delay.

**Current Protocol:**
Strict `chrony` NTP synchronization with logged offsets has been implemented for all subsequent Phase 2 and future hardware runs to ensure valid one-way delay calculations.
