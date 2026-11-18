"""Assemble the 10 main and 2 supplementary figures after the core renderer runs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from fig_oat import generate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OAT = ROOT / "reproduction/portable_original_analyses_v2/expected/oat_precision_v1/pointwise_intervals.csv"


def assemble(output, drawio=None):
    rendered = output / "core-work/publication_figures"
    if not rendered.is_dir():
        raise FileNotFoundError("Run reproduce.py figures --group current from the repository root.")
    current = output / "publication_figures"
    current.mkdir()
    plot = output / "oat-work"
    (plot / "reproducibility").mkdir(parents=True)
    (plot / "figures").mkdir()
    shutil.copyfile(OAT, plot / "reproducibility/pointwise_intervals.csv")
    generate(plot)
    index = json.loads((ROOT / "figures/index.json").read_text("utf-8"))
    for item in index:
        name = item["file"]
        dest = current / name
        if item["number"] == "1":
            if drawio is None:
                shutil.copyfile(ROOT / "figures" / name, dest)
            else:
                subprocess.run([str(drawio.resolve()), "--export", "--format", "pdf", "--crop",
                                "--border", "2", "--output", str(dest),
                                str(HERE / "Fig_revision_framework.drawio")], check=True)
        elif item["number"] == "3":
            shutil.copyfile(plot / "figures" / name, dest)
        else:
            shutil.copyfile(rendered / name, dest)
        if not dest.is_file() or not dest.stat().st_size:
            raise RuntimeError(f"Missing figure {item['number']}: {name}")
    report = {
        "main_figures": 10, "supplementary_figures": 2, "new_simulation_runs": 0,
        "framework": "draw.io export" if drawio else "copied published PDF",
        "figure_3": "rendered from the archived three-seed OAT intervals",
        "publication_directory": "publication_figures",
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(current.iterdir())},
    }
    (output / "reproduction_result.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(f"Manuscript figures: 10 main and 2 supplementary PDFs in {current}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--drawio", type=Path)
    args = parser.parse_args()
    assemble(args.output, args.drawio)
