"""Redraw the original seed-42 waiting shares without raster title masking."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.text import Text
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DATA_SHA = "e6d2b2c4b81dd58702f3022102f917252a1a3702483a37e450d14d67e846ecf4"


def data_rows(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_DATA_SHA:
        raise ValueError("The frozen waiting-share table has changed")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    total = sum(float(r["cumulative_waiting"]) for r in rows)
    for row in rows:
        assert abs(float(row["waiting_share"]) - float(row["cumulative_waiting"]) / total) < 1e-12
    assert abs(sum(float(r["waiting_share"]) for r in rows) - 1) < 1e-12
    assert all(float(a["waiting_share"]) >= float(b["waiting_share"])
               for a, b in zip(rows, rows[1:]))
    return rows


def draw(rows):
    style = {"font.family": "DejaVu Sans", "font.size": 10,
             "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 10,
             "axes.spines.top": False, "axes.spines.right": False,
             "axes.edgecolor": "#687277", "axes.linewidth": .6,
             "axes.grid": False, "figure.facecolor": "white",
             "axes.facecolor": "white", "savefig.facecolor": "white"}
    with plt.rc_context(style):
        fig, ax = plt.subplots(figsize=(8, 4.7), dpi=100)
        fig.subplots_adjust(left=.105, right=.975, bottom=.23, top=.965)
        values = [100 * float(r["waiting_share"]) for r in rows[:12]]
        bars = ax.bar(range(12), values, color="#AD722B", width=.70)
        labels = [ax.text(i, v + .27, f"{v:.1f}", ha="center", va="bottom", fontsize=9)
                  for i, v in enumerate(values)]
        ax.set_xticks(range(12), [r["edge"] for r in rows[:12]],
                      rotation=45, ha="right", rotation_mode="anchor")
        ax.set_ylabel("Share of network cumulative waiting (%)")
        ax.set_ylim(0, 20.5)
        ax.set_yticks(np.arange(0, 21, 5))
        ax.set_xlim(-.65, 11.65)
        ax.tick_params(axis="x", length=3)
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        outside = []
        for artist in fig.findobj(Text):
            if not artist.get_visible() or not artist.get_text().strip():
                continue
            box = artist.get_window_extent(renderer)
            if box.x0 < 0 or box.y0 < 0 or box.x1 > fig.bbox.width or box.y1 > fig.bbox.height:
                outside.append(artist.get_text())
        if outside:
            raise ValueError(f"Text outside the figure canvas: {outside}")
        for bar, value, label in zip(bars, values, labels):
            assert bar.get_height() == value
            assert bar.get_y() == 0 and value < ax.get_ylim()[1]
            assert label.get_window_extent(renderer).y1 < ax.bbox.y1
        return fig, {"bar_values_pct": values,
                     "edge_labels": [r["edge"] for r in rows[:12]],
                     "axis_y_limits": list(ax.get_ylim()),
                     "outside_canvas_text": outside,
                     "canvas_inches": [8, 4.7], "dpi": 600,
                     "all_bar_tops_and_value_labels_inside_axes": True,
                     "raster_mask_or_crop_applied": False,
                     "denominator": "cumulative waiting summed over the complete frozen edge table",
                     "total_source_edges": len(rows),
                     "seed": 42, "configuration": "original", "window_s": [0, 3600]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "audit/stage29_figures")
    args = parser.parse_args()
    source = ROOT / "frozen/data/baseline_edge_bottleneck.csv"
    fig, record = draw(data_rows(source))
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / "Fig08_baseline_edge_bottleneck.png"
    fig.savefig(output, dpi=600)
    plt.close(fig)
    record.update(source=str(source.relative_to(ROOT)), source_sha256=EXPECTED_DATA_SHA,
                  png_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  matplotlib_version=matplotlib.__version__)
    (args.output / "verification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
