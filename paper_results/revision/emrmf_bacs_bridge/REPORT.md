PRIMARY: BACS+ vs EMRMF (published parameters): 27.1 %, p = 1.00e-05, CONFIRMED

# EMRMF to BACS+ Controlled Bridge Report

## 1. Executive Summary

EMRMF (*Enhanced Multi-Robot Map Fusion*, Saber et al. 2026) established trust-weighted multi-robot constraint fusion. In this controlled bridge evaluation, BACS+ achieved a **27.1%** map-alignment RMSE reduction relative to published EMRMF under duty-cycle limited LoRa channels.

- **Primary Comparison**: BACS+ vs EMRMF reference
- **Primary Endpoint**: Map-alignment RMSE pooled across wireless conditions
- **Mean Improvement**: 27.1% reduction in map-alignment RMSE ($p < 0.001$)
- **Modelling Assumption**: FIFO constraint candidate transmission is adopted for EMRMF because published EMRMF did not specify an airtime constraint selection rule under duty-cycle limited channels.

---

## 2. Key Observations

1. **Airtime Bottleneck Handling**: Under scarce wireless airtime (1% EU868 duty-cycle ceiling), FIFO candidate transmission in EMRMF causes queue deferrals to accumulate. BACS+ ranks candidates by utility density ($\hat{I}_+ / T_{\text{air}}$) and filters out low-trust candidates ($\hat{\theta} < 0.05$).
2. **Observability Deficit Integration**: By incorporating the pair observability deficit $O_{ij} = \exp(-n_{ij} / 6.0)$, BACS+ prevents airtime starvation between robot pairs whose relative spatial transform remains under-constrained, preserving map alignment across the multi-robot team.
