from pathlib import Path
import csv
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "manuscript_working/figures"
INK = "#20252b"
MUTED = "#66717d"
WEATHER_DECOMPOSITION = ROOT / "frozen/data/weather_decomposition_summary.csv"
def setup() -> None:
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.edgecolor': INK, 'axes.labelcolor': INK, 'xtick.color': MUTED, 'ytick.color': MUTED, 'svg.fonttype': 'none', 'pdf.fonttype': 42})

def build_weather_decomposition() -> None:
    """Match the weather panel's canvas and plotting area to the trade-off panel."""
    labels = {'weather_heavy_rain': 'Combined heavy rain', 'weather_randomness_only': 'Stochasticity only', 'weather_accel_decel_only': 'Accel./decel. only', 'weather_no_randomness': 'Speed + accel./decel.', 'weather_speed_only': 'Speed only'}
    rows_by_name = {}
    with WEATHER_DECOMPOSITION.open(newline='', encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            rows_by_name[row['scenario']] = row
    wanted = ['weather_speed_only', 'weather_no_randomness', 'weather_accel_decel_only', 'weather_randomness_only', 'weather_heavy_rain']
    values = [float(rows_by_name[name]['dq_mean']) for name in wanted]
    fig = plt.figure(figsize=(9.4, 4.6))
    ax = fig.add_axes([0.15, 0.17, 0.66, 0.79])
    bars = ax.barh(range(len(wanted)), values, color='#c61f1f', height=0.7)
    ax.set_yticks(range(len(wanted)))
    ax.set_yticklabels([labels[name] for name in wanted], fontsize=8.6)
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_xlabel('Mean throughput change from seed-matched baseline (%)')
    ax.set_xlim(min(-17.0, min(values) - 1.0), 1.0)
    ax.grid(False)
    for bar, value in zip(bars, values):
        y = bar.get_y() + bar.get_height() / 2
        if value < -4:
            ax.text(value + 0.35, y, f'{value:.1f}%', va='center', ha='left', fontsize=8.2, color='white')
        else:
            ax.text(value - 0.2, y, f'{value:.1f}%', va='center', ha='right', fontsize=8.2, color=INK)
    fig.savefig(FIG / 'Fig23_weather_decomposition.png', dpi=340, facecolor='white')
    fig.savefig(FIG / 'Fig23_weather_decomposition.pdf', facecolor='white')
    fig.savefig(FIG / 'Fig23_weather_decomposition.svg', facecolor='white')
    plt.close(fig)
