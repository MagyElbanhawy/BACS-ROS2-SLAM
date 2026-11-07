#!/usr/bin/env python3
"""
Reproduces statistical comparisons between FIFO and BACS+ scheduling policies.
NOTE: Historical sessions were recorded independently. We treat these as 
INDEPENDENT samples using Mann-Whitney U test. Analysis is EXPLORATORY due 
to potential session-level dependence.
"""
import pandas as pd
import numpy as np
from scipy import stats
import argparse

def compute_cliffs_delta(x, y):
    total = 0
    for xi in x:
        for yj in y:
            if xi > yj: total += 1
            elif xi < yj: total -= 1
    return total / (len(x) * len(y))

def compute_independent_statistics(csv_path, output_path):
    print(f"🔍 Loading physical experiment results from: {csv_path}")
    df = pd.read_csv(csv_path)
    
    fifo_data = df[df['policy'] == 'FIFO']['deferral_mean_s'].dropna()
    bacs_plus_data = df[df['policy'] == 'BACS+']['deferral_mean_s'].dropna()
    
    n_fifo, n_bacs_plus = len(fifo_data), len(bacs_plus_data)
    
    if n_fifo == 0 or n_bacs_plus == 0:
        print("❌ Error: Could not find both FIFO and BACS+ data.")
        return

    statistic, p_value = stats.mannwhitneyu(fifo_data, bacs_plus_data, alternative='two-sided')
    cliffs_delta = compute_cliffs_delta(fifo_data.values, bacs_plus_data.values)
    
    results = {
        'metric': ['mean_scheduler_deferral_s'],
        'comparison': ['FIFO vs BACS+ (Independent)'],
        'n_fifo': [n_fifo], 'n_bacs_plus': [n_bacs_plus],
        'test_name': ['mannwhitney_u'], 'test_statistic': [statistic],
        'p_value': [p_value], 'cliffs_delta': [cliffs_delta],
        'status': ['COMPUTED'],
        'reason': ['Exploratory independent analysis (separate sessions); session-level dependence possible.']
    }
    
    pd.DataFrame(results).to_csv(output_path, index=False)
    print(f"✅ Saved to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # Sensible defaults so reproduce_all.py works without arguments
    parser.add_argument("--input", type=str, default="paper_results/physical/timing_per_run.csv")
    parser.add_argument("--output", type=str, default="paper_results/physical/physical_statistics.csv")
    args = parser.parse_args()
    compute_independent_statistics(args.input, args.output)
