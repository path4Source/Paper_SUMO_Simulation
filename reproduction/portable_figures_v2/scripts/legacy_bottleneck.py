from __future__ import annotations
from pathlib import Path
import csv
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "manuscript_working/figures"
import pandas as pd
from PIL import Image, ImageChops, ImageDraw
DATA_DIR = ROOT / "frozen/data"
FIG_DIR = FIG
def apply_paper_style() -> None:
    """Use one publication figure font scale across all generated figures."""
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'axes.titlesize': 11, 'axes.labelsize': 9, 'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 8, 'figure.dpi': 140, 'savefig.dpi': 320, 'axes.grid': False, 'axes.facecolor': 'white', 'figure.facecolor': 'white', 'savefig.facecolor': 'white', 'axes.edgecolor': '#374151', 'axes.titleweight': 'normal'})
def plot_bottleneck() -> None:
    path = DATA_DIR / 'baseline_edge_bottleneck.csv'
    if not path.exists():
        return
    df = pd.read_csv(path).head(12)
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    ax.bar(df['edge'], df['waiting_share'] * 100.0, color='#ea580c')
    ax.set_ylabel('Waiting share (%)')
    ax.tick_params(axis='x', labelrotation=45, labelsize=8)
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / 'Fig08_baseline_edge_bottleneck.png', dpi=300)
    plt.close(fig)
def erase_internal_titles(only: set[str] | None=None) -> None:
    """Remove redundant plot-level titles; manuscript captions carry the title."""
    specs = {'Fig02_sumo_oat_throughput.png': ((0.0, 0.0, 1.0, 0.095), 0.055), 'Fig09_sumo_capacity_dominance_index.png': ((0.0, 0.0, 1.0, 0.105), 0.06), 'Fig18_discharge_proxy_rounded_v2.png': ((0.25, 0.0, 0.87, 0.065), 0.0), 'Fig04_scirep_robustness.png': ((0.0, 0.0, 0.62, 0.115), 0.0), 'Fig07_capacity_delay_tradeoff.png': ((0.18, 0.0, 0.75, 0.06), 0.0), 'Fig23_weather_decomposition.png': ((0.0, 0.0, 1.0, 0.115), 0.07), 'Fig16_factorial_interactions.png': ((0.0, 0.0, 1.0, 0.095), 0.055), 'Fig03_capacity_sensitivity_ranking.png': ((0.0, 0.0, 1.0, 0.095), 0.055), 'Fig08_baseline_edge_bottleneck.png': ((0.0, 0.0, 1.0, 0.105), 0.06), 'FigS01_scirep_full_oat.png': ((0.0, 0.0, 1.0, 0.125), 0.075), 'Fig13_multiseed_scenario_stability.png': ((0.0, 0.0, 1.0, 0.105), 0.055), 'Fig14_multiseed_factor_stability.png': ((0.0, 0.0, 1.0, 0.105), 0.055), 'Fig21_keyseed_stability.png': ((0.32, 0.0, 0.92, 0.065), 0.0), 'Fig19_co2_intensity_risk.png': ((0.0, 0.0, 1.0, 0.105), 0.055), 'Fig10_signal_timing_effects.png': ((0.0, 0.0, 1.0, 0.105), 0.055), 'Fig11_behavior_vehicle_weather_effects.png': ((0.0, 0.0, 1.0, 0.105), 0.055), 'Fig04_factor_response_curves.png': ((0.0, 0.0, 1.0, 0.09), 0.045), 'Fig05_interaction_heatmap.png': ((0.0, 0.0, 1.0, 0.095), 0.05), 'Fig06_surrogate_factor_importance.png': ((0.0, 0.0, 1.0, 0.095), 0.05)}
    for name, (box_coords, crop_top) in specs.items():
        if only is not None and name not in only:
            continue
        x1, y1, x2, y2 = box_coords
        path = FIG / name
        image = Image.open(path).convert('RGB')
        w, h = image.size
        draw = ImageDraw.Draw(image)
        draw.rectangle((int(w * x1), int(h * y1), int(w * x2), int(h * y2)), fill='white')
        if crop_top:
            image = image.crop((0, int(h * crop_top), w, h))
        image.save(path, dpi=(340, 340), optimize=True)

def trim_raster_figure_margins() -> None:
    """Apply one consistent, tight content boundary to raster-only figures."""
    names = ['Fig02_sumo_oat_throughput.png', 'Fig09_sumo_capacity_dominance_index.png', 'Fig18_discharge_proxy_rounded_v2.png', 'Fig03_scirep_main_findings.png', 'Fig04_scirep_robustness.png', 'Fig16_factorial_interactions.png', 'Fig03_capacity_sensitivity_ranking.png', 'Fig08_baseline_edge_bottleneck.png', 'Fig06_scirep_priorities.png', 'FigS01_scirep_full_oat.png', 'Fig13_multiseed_scenario_stability.png', 'Fig14_multiseed_factor_stability.png', 'Fig21_keyseed_stability.png', 'Fig19_co2_intensity_risk.png', 'Fig10_signal_timing_effects.png', 'Fig11_behavior_vehicle_weather_effects.png', 'Fig04_factor_response_curves.png', 'Fig05_interaction_heatmap.png', 'Fig06_surrogate_factor_importance.png']
    for name in names:
        path = FIG / name
        if not path.exists():
            continue
        image = Image.open(path).convert('RGB')
        white = Image.new('RGB', image.size, 'white')
        difference = ImageChops.difference(image, white).convert('L')
        mask = difference.point(lambda value: 255 if value > 7 else 0)
        bbox = mask.getbbox()
        if bbox is None:
            continue
        left, top, right, bottom = bbox
        pad = max(12, int(min(image.size) * 0.012))
        crop = (max(0, left - pad), max(0, top - pad), min(image.width, right + pad), min(image.height, bottom + pad))
        image.crop(crop).save(path, dpi=(340, 340), optimize=True)
