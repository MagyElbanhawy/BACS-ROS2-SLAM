"""SYNTHETIC-FIXTURE script -- not part of the physical evidence chain.

Moved from scripts/repro/compute_map_alignment.py in revision v3. It reads the
synthetic ``fused_HWS-1xx-*.csv`` fixtures in ``synthetic_test_fixtures/hardware_v2``
and compares the limo01-limo02 relative position against zero, which is only
meaningful for those fixtures. Physical map alignment is computed by
``analysis/physical/map_alignment.py`` (CLI: ``scripts/repro/compute_map_alignment.py``).
"""
import argparse
import csv
import os
import glob
import numpy as np
from scipy.stats import wilcoxon

def load_fused_csv(csv_path):
    """Loads a fused CSV and returns a list of (t, x1, y1, x2, y2) co-located pairs."""
    data = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        # Group by timestamp
        poses_at_t = {}
        for row in reader:
            t = float(row['stamp_ns'])
            if t not in poses_at_t:
                poses_at_t[t] = {}
            robot = row['robot']
            poses_at_t[t][robot] = (float(row['est_x']), float(row['est_y']))
            
        for t, robots in poses_at_t.items():
            if 'limo01' in robots and 'limo02' in robots:
                data.append((t, robots['limo01'][0], robots['limo01'][1], robots['limo02'][0], robots['limo02'][1]))
    return data

def kabsch_2d(P, Q):
    """Finds optimal 2D rotation matrix mapping P to Q."""
    centroid_P = np.mean(P, axis=0)
    centroid_Q = np.mean(Q, axis=0)
    P_c = P - centroid_P
    Q_c = Q - centroid_Q
    
    H = np.dot(P_c.T, Q_c)
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(np.dot(Vt.T, U.T)))
    R = np.dot(Vt.T, np.dot(np.diag([1, d]), U.T))
    return R, centroid_P, centroid_Q

def compute_rmse_for_csv(csv_path):
    data = load_fused_csv(csv_path)
    if len(data) < 2:
        return None, 0, 0.0
        
    # Extract fused relative poses and Vicon relative poses
    fused_rel = np.array([[d[3]-d[1], d[4]-d[2]] for d in data])
    
    # Fixture convention: the reference relative position is zero.
    vicon_rel = np.zeros_like(fused_rel)
    
    R, cP, cQ = kabsch_2d(fused_rel, vicon_rel)
    fused_rot = np.dot(fused_rel - cP, R.T) + cQ
    
    errors = np.linalg.norm(fused_rot - vicon_rel, axis=1)
    rmse = np.sqrt(np.mean(errors**2))
    fitted_rot_deg = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
    
    return rmse, len(data), fitted_rot_deg

def cliffs_delta(candidate, reference):
    """Cliff's delta of (candidate, reference); negative => candidate lower."""
    c, r = np.asarray(candidate, float), np.asarray(reference, float)
    diff = c[:, None] - r[None, :]
    return float((np.sum(diff > 0) - np.sum(diff < 0)) / diff.size)


def run(poses_glob, segmentation_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    
    # Read segmentation file
    runs = []
    with open(segmentation_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            runs.append(row)
            
    per_run_results = []
    
    for run_info in runs:
        run_id = run_info['run']
        policy = run_info['policy']
        session_name = f"HWS-{run_id}-{policy}"
        csv_path = f"synthetic_test_fixtures/hardware_v2/{session_name}/fused_{session_name}.csv"
        
        if not os.path.exists(csv_path):
            # Fallback to glob if path structure differs
            files = glob.glob(f"synthetic_test_fixtures/hardware_v2/*-{run_id}-{policy}/fused_*.csv")
            if files:
                csv_path = files[0]
            else:
                continue
                
        rmse, pairs, rot = compute_rmse_for_csv(csv_path)
        if rmse is not None:
            per_run_results.append({
                'policy': policy,
                'run': int(run_id),
                'radius_m': 0.5,
                'session': session_name,
                'samples': pairs * 2,
                'colocation_pairs': pairs,
                'map_alignment_rmse_m': rmse,
                'relative_rmse_all_samples_m': rmse,
                'fitted_rotation_deg': rot,
                'status': 'COMPUTED'
            })
            
    # Write Per-Run CSV
    per_run_path = os.path.join(out_dir, "map_alignment_per_run.csv")
    with open(per_run_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'policy', 'run', 'radius_m', 'session', 'samples', 'colocation_pairs', 
            'map_alignment_rmse_m', 'relative_rmse_all_samples_m', 'fitted_rotation_deg', 'status'
        ])
        writer.writeheader()
        writer.writerows(per_run_results)
        
    # Compute Summary
    policies = ['FIFO', 'BACS', 'BACS+']
    summary = {}
    for p in policies:
        rmses = [r['map_alignment_rmse_m'] for r in per_run_results if r['policy'] == p]
        summary[p] = {'mean': np.mean(rmses), 'std': np.std(rmses), 'data': rmses}
        
    with open(os.path.join(out_dir, "map_alignment_summary.csv"), 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['policy', 'n_runs', 'mean_m', 'std_m', 'ci95_low_m', 'ci95_high_m', 'median_m', 'p25_m', 'p75_m', 'status'])
        for p, s in summary.items():
            writer.writerow([p, 10, s['mean'], s['std'], s['mean']-1.96*s['std']/np.sqrt(10), s['mean']+1.96*s['std']/np.sqrt(10), np.median(s['data']), np.percentile(s['data'], 25), np.percentile(s['data'], 75), 'COMPUTED'])
            
    # Compute Statistics
    with open(os.path.join(out_dir, "map_alignment_statistics.csv"), 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'reference', 'candidate', 'n_reference', 'n_candidate', 'n_pairs', 'mean_reference_m', 'mean_candidate_m', 'relative_change_of_means', 'cliffs_delta', 'wilcoxon_p_two_sided', 'pairing', 'status'])
        
        w_stat, p_val = wilcoxon(summary['FIFO']['data'], summary['BACS+']['data'])
        delta = cliffs_delta(summary['BACS+']['data'], summary['FIFO']['data'])
        rel_change = (summary['BACS+']['mean'] - summary['FIFO']['mean']) / summary['FIFO']['mean']
        writer.writerow(['map_alignment_rmse_m', 'FIFO', 'BACS+', 10, 10, 10, summary['FIFO']['mean'], summary['BACS+']['mean'], rel_change, delta, p_val, 'matched_block_design', 'COMPUTED'])
        
        w_stat2, p_val2 = wilcoxon(summary['FIFO']['data'], summary['BACS']['data'])
        rel_change2 = (summary['BACS']['mean'] - summary['FIFO']['mean']) / summary['FIFO']['mean']
        delta2 = cliffs_delta(summary['BACS']['data'], summary['FIFO']['data'])
        writer.writerow(['map_alignment_rmse_m', 'FIFO', 'BACS', 10, 10, 10, summary['FIFO']['mean'], summary['BACS']['mean'], rel_change2, delta2, p_val2, 'matched_block_design', 'COMPUTED'])

    print(f"Wrote map_alignment_*.csv to {out_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--poses", required=True, help="Glob pattern for fused CSVs")
    parser.add_argument("--segmentation", required=True, help="run_segmentation.csv")
    parser.add_argument("--out", required=True, help="Output directory")
    args = parser.parse_args()
    run(args.poses, args.segmentation, args.out)