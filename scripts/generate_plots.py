"""
Generate SVG Learning Curves and Report Data Summaries.
Generates standalone vector SVG plots for Map Exploration Coverage and Battle Win Rate.
No matplotlib required — pure Python SVG generation.
"""

import os
import csv
import json


def generate_svg_plot(data_x, data_y, title, x_label, y_label, out_path, baseline_val=None, baseline_label=None, width=720, height=360):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    margin = {"top": 45, "right": 40, "bottom": 50, "left": 65}
    pw = width - margin["left"] - margin["right"]
    ph = height - margin["top"] - margin["bottom"]

    min_x, max_x = min(data_x), max(data_x)
    min_y = 0.0
    max_y = max(max(data_y), baseline_val if baseline_val else 0.0) * 1.15
    if max_y <= 0:
        max_y = 1.0

    def tx(x):
        return margin["left"] + (x - min_x) / (max_x - min_x if max_x > min_x else 1) * pw

    def ty(y):
        return margin["top"] + ph - (y - min_y) / (max_y - min_y if max_y > min_y else 1) * ph

    points = [f"{tx(x):.1f},{ty(y):.1f}" for x, y in zip(data_x, data_y)]
    poly_line = " ".join(points)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" style="background-color: #0f172a; font-family: ui-sans-serif, system-ui, sans-serif;">',
        f'  <!-- Title -->',
        f'  <text x="{width/2}" y="28" fill="#f8fafc" font-size="16" font-weight="600" text-anchor="middle">{title}</text>',
        f'  <!-- Axes Grid -->',
    ]

    # Gridlines (5 horizontal)
    for i in range(5):
        y_val = min_y + i * (max_y - min_y) / 4.0
        y_pos = ty(y_val)
        svg.append(f'  <line x1="{margin["left"]}" y1="{y_pos:.1f}" x2="{width - margin["right"]}" y2="{y_pos:.1f}" stroke="#334155" stroke-dasharray="3,3" stroke-width="1"/>')
        svg.append(f'  <text x="{margin["left"] - 10}" y="{y_pos + 4:.1f}" fill="#94a3b8" font-size="11" text-anchor="end">{y_val:.2f}</text>')

    # X axis labels
    for i in range(5):
        x_val = min_x + i * (max_x - min_x) / 4.0
        x_pos = tx(x_val)
        svg.append(f'  <text x="{x_pos:.1f}" y="{height - margin["bottom"] + 20}" fill="#94a3b8" font-size="11" text-anchor="middle">{int(x_val)}</text>')

    # Axis Titles
    svg.append(f'  <text x="{width/2}" y="{height - 12}" fill="#cbd5e1" font-size="12" text-anchor="middle">{x_label}</text>')
    svg.append(f'  <text x="18" y="{height/2}" fill="#cbd5e1" font-size="12" text-anchor="middle" transform="rotate(-90 18 {height/2})">{y_label}</text>')

    # Baseline line (if present)
    if baseline_val is not None:
        by = ty(baseline_val)
        svg.append(f'  <!-- Baseline -->')
        svg.append(f'  <line x1="{margin["left"]}" y1="{by:.1f}" x2="{width - margin["right"]}" y2="{by:.1f}" stroke="#f59e0b" stroke-width="2" stroke-dasharray="6,4"/>')
        svg.append(f'  <text x="{width - margin["right"] - 8}" y="{by - 6:.1f}" fill="#f59e0b" font-size="11" text-anchor="end">{baseline_label or "Baseline"}: {baseline_val:.2f}</text>')

    # Training Data Line
    svg.append(f'  <!-- Data line -->')
    svg.append(f'  <polyline fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="{poly_line}"/>')

    # Legend
    svg.append(f'  <circle cx="{margin["left"] + 20}" cy="{margin["top"] + 15}" r="4" fill="#38bdf8"/>')
    svg.append(f'  <text x="{margin["left"] + 30}" y="{margin["top"] + 19}" fill="#e2e8f0" font-size="11">DQN Agent</text>')

    svg.append('</svg>')

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    print(f"Generated {out_path}")


def main():
    # 1. Map Learning Curve (Moving avg coverage)
    map_csv = "logs/map_training_log.csv"
    if os.path.exists(map_csv):
        eps, covs = [], []
        with open(map_csv, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    eps.append(int(row["episode"]))
                    covs.append(float(row["coverage"]))
                except (ValueError, KeyError):
                    continue
        if eps:
            # Compute 20-episode moving average
            window = 20
            smooth_cov = []
            for i in range(len(covs)):
                start = max(0, i - window + 1)
                smooth_cov.append(sum(covs[start:i+1]) / (i - start + 1))
            generate_svg_plot(
                eps, smooth_cov,
                title="Map DQN: Grid Coverage Progression (Overworld 1)",
                x_label="Training Episode",
                y_label="Map Tile Coverage Ratio",
                out_path="docs/assets/map_training_curve.svg",
                baseline_val=0.349,
                baseline_label="BFS Baseline (34.9%)"
            )

    # 2. Battle Learning Curve (Win Rate)
    battle_csv = "logs/battle_training_log.csv"
    if os.path.exists(battle_csv):
        eps, wrs = [], []
        with open(battle_csv, "r") as f:
            reader = csv.DictReader(f)
            wins = []
            for i, row in enumerate(reader):
                try:
                    ep = int(row["episode"])
                    res = row["result"]
                    wins.append(1.0 if res == "win" else 0.0)
                    if len(wins) > 200:
                        wins.pop(0)
                    eps.append(ep)
                    wrs.append(sum(wins) / len(wins))
                except (ValueError, KeyError):
                    continue
        if eps:
            # Subsample every 10 points for clean plot
            sub_eps = eps[::10]
            sub_wrs = wrs[::10]
            generate_svg_plot(
                sub_eps, sub_wrs,
                title="Battle DQN: 6v6 Win Rate Progression",
                x_label="Battle Episode",
                y_label="Rolling Win Rate (200-battle window)",
                out_path="docs/assets/battle_training_curve.svg",
                baseline_val=0.985,
                baseline_label="Greedy Heuristic (98.5%)"
            )


if __name__ == "__main__":
    main()
