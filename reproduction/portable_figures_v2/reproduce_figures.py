"""Reproduce active figures from included tables; never launch SUMO or LaTeX."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def within(path, root):
    return path == root or root in path.parents


def verify_manifest(root):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for relative, digest in manifest["files"].items():
        path = (root / relative).resolve()
        if not within(path, root.resolve()) or sha256(path) != digest:
            raise ValueError(f"Missing, altered or unsafe package file: {relative}")
    return manifest


def load_module(root, name):
    path = root / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def figure_trace(fig):
    """Record plotted coordinates, error-band paths and labels before raster export."""
    import numpy as np

    def values(value):
        return np.asarray(value).tolist()

    axes = []
    for ax in fig.axes:
        axes.append({
            "xlim": list(ax.get_xlim()), "ylim": list(ax.get_ylim()),
            "xlabel": ax.get_xlabel(), "ylabel": ax.get_ylabel(),
            "texts": [text.get_text() for text in ax.texts],
            "xticklabels": [text.get_text() for text in ax.get_xticklabels()],
            "yticklabels": [text.get_text() for text in ax.get_yticklabels()],
            "lines": [{"x": values(line.get_xdata()), "y": values(line.get_ydata())}
                      for line in ax.lines],
            "patches": [values(patch.get_path().vertices) for patch in ax.patches],
            "rectangle_data_bounds": [list(patch.get_bbox().bounds) for patch in ax.patches
                                      if hasattr(patch, "get_bbox")],
            "patch_extents": [list(patch.get_extents().bounds) for patch in ax.patches],
            "collections": [{"offsets": values(collection.get_offsets()),
                             "paths": [values(path.vertices) for path in collection.get_paths()]}
                            for collection in ax.collections],
        })
    return {"size_inches": values(fig.get_size_inches()), "axes": axes,
            "figure_texts": [text.get_text() for text in fig.texts]}


def run_group(root, group):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    output = root / "manuscript_working/figures"
    output.mkdir(parents=True, exist_ok=True)
    (root / "audit").mkdir(exist_ok=True)
    traces = root / "traces"
    traces.mkdir(exist_ok=True)
    original_save = Figure.savefig

    def png_only(figure, path, *args, **kwargs):
        target = Path(path).resolve()
        if not within(target, root.resolve()):
            raise ValueError(f"Output escaped package: {target}")
        if target.suffix.lower() != ".png":
            return
        figure.canvas.draw()
        (traces / (target.stem + ".json")).write_text(
            json.dumps(figure_trace(figure), indent=2), encoding="utf-8")
        return original_save(figure, target, *args, **kwargs)

    Figure.savefig = png_only
    try:
        plt.rcdefaults()
        module_names = {
            "scores": "plot_scores_stage8", "legacy": "plot_legacy_stage10",
            "cycle": "plot_core_cycle_check", "intervention": "plot_independent_intervention_v1",
            "horizon": "plot_horizon_v1", "weather": "legacy_weather",
            "bottleneck": "legacy_bottleneck",
        }
        module = load_module(root, module_names[group])
        if group == "scores":
            for name in ("scores", "robustness", "multiseed", "responses", "framework"):
                getattr(module, name)()
        elif group == "weather":
            module.setup()
            module.build_weather_decomposition()
        elif group == "bottleneck":
            module.apply_paper_style()
            module.plot_bottleneck()
            # The extracted generator already has no title. Masking its top would erase data.
            module.trim_raster_figure_margins()
        else:
            module.main()
    finally:
        Figure.savefig = original_save
        plt.close("all")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=["scores", "legacy", "cycle", "intervention", "horizon", "weather", "bottleneck"])
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = verify_manifest(root)
    if args.verify:
        print(json.dumps({"verified_files": len(manifest["files"]), "active_figures": len(manifest["figures"])}))
    if args.group:
        sys.path.insert(0, str(root / "scripts"))
        run_group(root, args.group)


if __name__ == "__main__":
    main()
