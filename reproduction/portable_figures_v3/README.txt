Current manuscript figures

This package reproduces the 14 numerical figures from the recorded tables and network geometry. The conceptual framework has an editable draw.io source and its verified PDF export. No new SUMO runs or manuscript compilation are performed.

Use a fresh copy of this directory. Install requirements.txt in Python 3.12, then run:

  python reproduce_figures.py --verify
  python reproduce_figures.py

Outputs appear in manuscript_working/figures as PDF, SVG and 450-dpi PNG for numerical figures. The framework PDF is copied from the verified reference unless --drawio is supplied with the installed draw.io executable path. This distinction is recorded in reproduction_result.json. To re-export the framework instead, use a fresh package copy:

  python reproduce_figures.py --drawio /path/to/draw.io

The plotting calculations are retained from the previous reproducibility package. current_style.py changes presentation only and verifies that data coordinates, bar extents and interval paths are unchanged. The resulting 14 numerical-trace hashes must also match the frozen references in expected/numerical_traces.json. Original inputs are checked before and after rendering. Source paths were relocated within this package; no absolute author-machine paths are required.

The current typography uses Arial. Install an appropriately licensed Arial font locally for identical typography; fonts are not redistributed here. Different font or rendering-library versions can change pixels without changing data. The recorded environment is Python 3.12, Matplotlib 3.11.2, NumPy 2.5.4 and Pillow 13.0.0. PDFs may differ in creation metadata between runs, so byte identity is checked for distributed assets and numerical traces, not promised for newly exported PDFs.

expected/ contains current reference PDF and PNG assets. sources/ contains only the editable conceptual framework. This package supersedes the older plotting appearance; it does not supersede archived experiments or change their results.
