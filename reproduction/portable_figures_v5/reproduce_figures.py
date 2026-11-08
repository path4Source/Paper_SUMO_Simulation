"""Reproduce the fifteen figures referenced by the fixed full-length manuscript."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--drawio", type=Path)
    args = parser.parse_args()
    legacy = load("legacy_renderer", ROOT / "reproduce_prior_figures.py")
    count = legacy.verify()
    if args.verify:
        print(json.dumps({"verified_inputs": count}))
        return
    output = ROOT / "manuscript_working/figures"
    if output.exists():
        raise FileExistsError("Use a fresh package copy; existing outputs are retained")
    output.mkdir(parents=True)
    audit = ROOT / "audit/figure_redesign_20261022"
    audit.mkdir(parents=True)
    sys.path.insert(0, str(ROOT / "scripts"))
    style = load("current_style", ROOT / "scripts/current_style.py")
    original_polish = style.polish
    def polish(fig, name):
        if name == "Fig_revision_three_seed_stage10":
            before = style.numerical_trace(fig)
            ax = fig.axes[0]
            labels = [label.get_text().replace("Bottleneck lane organization (lane-control variant)",
                                               "Lane-control variant") for label in ax.get_yticklabels()]
            ax.set_yticks(ax.get_yticks(), labels)
            assert style.numerical_trace(fig) == before
        return original_polish(fig, name)
    style.polish = polish
    style.main()
    actual = json.loads((audit / "figure_data_preservation.json").read_text())
    expected = json.loads((ROOT / "expected/numerical_traces.json").read_text())
    assert {r["figure"]: r["numerical_trace_sha256"] for r in actual["figures"]} == expected
    assert not actual["text_outside_canvas"]
    framework = "Fig_revision_framework"
    if args.drawio:
        subprocess.run([str(args.drawio.resolve()), "--export", "--format", "pdf", "--crop",
                        "--border", "2", "--output", str(output / f"{framework}.pdf"),
                        str(ROOT / f"sources/{framework}.drawio")], check=True)
        action = "exported_from_editable_source"
    else:
        shutil.copy2(ROOT / f"expected/{framework}.pdf", output / f"{framework}.pdf")
        action = "copied_verified_reference; editable_source_included"
    final = ROOT / "publication_figures"
    final.mkdir()
    index = json.loads((ROOT / "expected/current_index.json").read_text())
    assert len(index) == 15
    for item in index:
        shutil.copy2(output / item["file"], final / item["file"])
    legacy.verify()
    report = dict(current_figures=15, current_data_figures=14, framework=action,
                  new_simulations=0, publication_directory="publication_figures", numerical_traces_verified=True)
    (ROOT / "reproduction_result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
