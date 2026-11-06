#!/usr/bin/env python3
"""
Reproduces statistical comparisons between FIFO and BACS+ scheduling policies.

NOTE: Historical FIFO and BACS+ sessions were recorded independently (separate dates/sessions).
Therefore, we treat these as INDEPENDENT samples using Mann-Whitney U test,
NOT as paired observations. Run IDs do not establish temporal pairing.
"""
import pandas as pd
import numpy as np
from scipy import stats
import argparse

def compute_independent_statistics(csv_path, output_path):
    print("🔍 Loading physical experiment results...")
    df = pd.read_csv(csv_path)
    
    # Separate FIFO and BACS+ runs (treat as independent samples)
    fifo_data = df[df['policy'] == 'FIFO']['metric_value'].dropna()
    bacs_plus_data = df[df['policy'] == 'BACS+']['metric_value'].dropna()
    
    n_fifo = len(fifo_data)
    n_bacs_plus = len(bacs_plus_data)
    
    print(f"  FIFO runs: {n_fifo}")
    print(f"  BACS+ runs: {n_bacs_plus}")
    
    # Use Mann-Whitney U test for independent samples (non-parametric)
    statistic, p_value = stats.mannwhitneyu(fifo_data, bacs_plus_data, alternative='two-sided')
    
    # Calculate effect size (Cliff's Delta)
    cliffs_delta = compute_cliffs_delta(fifo_data.values, bacs_plus_data.values)
    
    results = {
        'n_fifo': [n_fifo],
        'n_bacs_plus': [n_bacs_plus],
        'test_name': ['mannwhitney_u'],
        'test_statistic': [statistic],
        'p_value': [p_value],
        'cliffs_delta': [cliffs_delta],
        'interpretation': ['independent_samples']
    }
    
    results_df = pd.DataFrame(results)
    results_df.to_csv(output_path, index=False)
    
    print(f"\n✅ Statistical results saved to: {output_path}")
    print(f"   Mann-Whitney U Statistic: {statistic:.4f}")
    print(f"   p-value: {p_value:.4f}")
    print(f"   Cliff's Delta: {cliffs_delta:.4f}")
    print(f"\n💡 These are INDEPENDENT samples (not paired).")

def compute_cliffs_delta(x, y):
    """Compute Cliff's Delta effect size."""
    total = 0
    for xi in x:
        for yj in y:
            if xi > yj:
                total += 1
            elif xi < yj:
                total -= 1
    return total / (len(x) * len(y))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, required=True, help="Path to physical results CSV")
    parser.add_argument("--output", type=str, required=True, help="Path to output statistics CSV")
    args = parser.parse_args()
    
    compute_independent_statistics(args.input, args.output)
