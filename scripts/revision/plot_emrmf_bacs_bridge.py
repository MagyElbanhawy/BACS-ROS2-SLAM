"""
Plotting Script for EMRMF vs. BACS+ Bridge Experiment Figures.

Reads CSVs in `paper_results/revision/emrmf_bacs_bridge/` and generates:
- fig_emrmf_to_bacs_evolution.png
- fig_emrmf_vs_bacs_alignment.png
- fig_emrmf_vs_bacs_by_condition.png
- fig_emrmf_vs_bacs_scalability.png

Usage:
  python scripts/revision/plot_emrmf_bacs_bridge.py
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def set_plot_style():
    """Publication-quality matplotlib styling."""
    plt.rcParams.update({
        'font.sans-serif': 'DejaVu Sans',
        'font.family': 'sans-serif',
        'figure.dpi': 300,
        'savefig.dpi': 300,
        'axes.edgecolor': '#333333',
        'axes.linewidth': 0.8,
        'axes.grid': True,
        'grid.color': '#e5e5e5',
        'grid.linestyle': '--',
        'grid.linewidth': 0.5,
        'legend.frameon': True,
        'legend.facecolor': '#ffffff',
        'legend.edgecolor': '#cccccc',
        'font.size': 10,
        'axes.labelsize': 11,
        'axes.titlesize': 12,
        'xtick.labelsize': 9,
        'ytick.labelsize': 9,
    })


def plot_alignment_comparison(df_raw: pd.DataFrame, out_dir: Path):
    """Figure: Primary Map-Alignment RMSE Comparison (EMRMF vs BACS+)."""
    fig, ax = plt.subplots(figsize=(6, 4.5))

    sub = df_raw[df_raw.policy.isin(["emrmf_reference", "bacs_plus"])].copy()
    sub["policy_label"] = sub.policy.map({
        "emrmf_reference": "EMRMF\nReference",
        "bacs_plus": "BACS+\n(Frozen Final)"
    })

    policies = ["EMRMF\nReference", "BACS+\n(Frozen Final)"]
    data = [sub[sub.policy_label == p]["align_rmse"].dropna().to_numpy() for p in policies]

    bp = ax.boxplot(data, labels=policies, patch_artist=True, widths=0.4,
                    boxprops=dict(facecolor='#e6f2ff', color='#0066cc', linewidth=1.2),
                    medianprops=dict(color='#cc0000', linewidth=1.5),
                    whiskerprops=dict(color='#0066cc', linewidth=1.2),
                    capprops=dict(color='#0066cc', linewidth=1.2))

    # Color BACS+ box distinctively
    if len(bp['boxes']) > 1:
        bp['boxes'][1].set_facecolor('#e6ffe6')
        bp['boxes'][1].set_edgecolor('#009933')

    ax.set_ylabel("Map-Alignment RMSE [m]")
    ax.set_title("Controlled Head-to-Head Comparison")
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.2f'))

    plt.tight_layout()
    fig.savefig(out_dir / "fig_emrmf_vs_bacs_alignment.png")
    plt.close(fig)


def plot_by_condition(df_raw: pd.DataFrame, out_dir: Path):
    """Figure: Alignment RMSE by Channel Condition (C0-C3)."""
    fig, ax = plt.subplots(figsize=(7, 4.5))

    sub = df_raw[df_raw.policy.isin(["emrmf_reference", "bacs_plus"])].copy()
    g = sub.groupby(["condition", "policy"])["align_rmse"].mean().unstack()

    conds = ["C0", "C1", "C2", "C3"]
    g = g.reindex(conds)

    x = np.arange(len(conds))
    width = 0.35

    y_emrmf = g["emrmf_reference"].to_numpy() if "emrmf_reference" in g.columns else np.zeros(len(conds))
    y_bacs = g["bacs_plus"].to_numpy() if "bacs_plus" in g.columns else np.zeros(len(conds))

    ax.bar(x - width/2, y_emrmf, width, label="EMRMF Reference", color="#4a90e2")
    ax.bar(x + width/2, y_bacs, width, label="BACS+ (Frozen)", color="#50e3c2")

    ax.set_xlabel("Channel Condition")
    ax.set_ylabel("Mean Map-Alignment RMSE [m]")
    ax.set_xticks(x)
    ax.set_xticklabels(["C0\n(Ideal)", "C1\n(10% Loss)", "C2\n(30% Loss)", "C3\n(Burst & Delay)"])
    ax.legend()
    ax.set_title("Performance across Wireless Channel Conditions")

    plt.tight_layout()
    fig.savefig(out_dir / "fig_emrmf_vs_bacs_by_condition.png")
    plt.close(fig)


def plot_scalability(df_raw: pd.DataFrame, out_dir: Path):
    """Figure: Alignment RMSE Scaling across Robot Counts (N=2..5)."""
    fig, ax = plt.subplots(figsize=(6.5, 4.5))

    sub = df_raw[df_raw.policy.isin(["emrmf_reference", "bacs_plus"])].copy()
    g = sub.groupby(["n_robots", "policy"])["align_rmse"].mean().unstack()

    counts = [2, 3, 4, 5]
    g = g.reindex(counts)

    y_emrmf = g["emrmf_reference"].to_numpy() if "emrmf_reference" in g.columns else np.zeros(len(counts))
    y_bacs = g["bacs_plus"].to_numpy() if "bacs_plus" in g.columns else np.zeros(len(counts))

    ax.plot(counts, y_emrmf, 'o--', color="#d9534f", linewidth=1.8, label="EMRMF Reference")
    ax.plot(counts, y_bacs, 's-', color="#5cb85c", linewidth=2.0, label="BACS+ (Frozen)")

    ax.set_xlabel("Number of Robots (N)")
    ax.set_ylabel("Mean Map-Alignment RMSE [m]")
    ax.set_xticks(counts)
    ax.set_title("Scalability Progression (N = 2 to 5)")
    ax.legend()

    plt.tight_layout()
    fig.savefig(out_dir / "fig_emrmf_vs_bacs_scalability.png")
    plt.close(fig)


def plot_evolution(out_dir: Path):
    """Figure: Conceptual/Metric Research Evolution Progression."""
    fig, ax = plt.subplots(figsize=(7, 4))

    stages = [
        "1. Published\nEMRMF",
        "2. Bandwidth\nLimitation",
        "3. BACS\n(Scheduler)",
        "4. BACS+\n(Observability)",
        "5. Frozen\nBACS+ Baseline"
    ]
    ax.axis("off")
    for i, s in enumerate(stages):
        ax.text(i * 2.0, 0.5, s, ha='center', va='center', bbox=dict(boxstyle="round,pad=0.5", fc="#f0f4f8", ec="#0066cc", lw=1.5))
        if i < len(stages) - 1:
            ax.annotate("", xy=((i + 1) * 2.0 - 0.7, 0.5), xytext=(i * 2.0 + 0.7, 0.5),
                        arrowprops=dict(arrowstyle="->", lw=1.5, color="#333333"))

    ax.set_xlim(-1, len(stages) * 2.0 - 1)
    ax.set_ylim(0, 1)
    ax.set_title("Scientific Evolution from EMRMF to Frozen BACS+", pad=20)

    plt.tight_layout()
    fig.savefig(out_dir / "fig_emrmf_to_bacs_evolution.png")
    plt.close(fig)


def generate_all_plots(out_dir: Path):
    """Load raw data and plot all figures."""
    raw_path = out_dir / "raw.csv"
    if not raw_path.exists():
        print(f"Plotting skipped: {raw_path} does not exist yet.")
        return

    set_plot_style()
    df_raw = pd.read_csv(raw_path)

    plot_alignment_comparison(df_raw, out_dir)
    plot_by_condition(df_raw, out_dir)
    plot_scalability(df_raw, out_dir)
    plot_evolution(out_dir)

    print(f"Generated all bridge experiment figures in {out_dir}/")


def main():
    out_dir = ROOT / "paper_results" / "revision" / "emrmf_bacs_bridge"
    generate_all_plots(out_dir)


if __name__ == "__main__":
    main()
