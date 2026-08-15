"""Run this as the last cell after `python -m eval.ragas_eval` finishes on
Kaggle. Copies the eval report(s) into /kaggle/working/ so they're
automatically packaged as the notebook's downloadable Output once you hit
"Save Version" - this is the reliable way to get a file out of a Kaggle
notebook: anything under /kaggle/working/ at the end of a run appears on
the notebook's Output tab, no manual download-click needed during the run
itself (a JS-triggered browser auto-download is unreliable during a
headless Save Version run, since there's no live browser tab guaranteed
to execute it - this sidesteps that entirely).

Usage (paste as a cell, or `!python kaggle/collect_results.py`):
    python kaggle/collect_results.py
"""

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KAGGLE_OUTPUT_DIR = Path("/kaggle/working")

REPORTS = [
    "data/eval/ragas_report.json",
    "data/eval/routing_report.json",
    "data/eval/latency_report.json",
    "data/eval/synthesis_reports.json",
]

if __name__ == "__main__":
    KAGGLE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for rel_path in REPORTS:
        src = REPO_ROOT / rel_path
        if not src.exists():
            print(f"skip (not found): {rel_path}")
            continue
        dest = KAGGLE_OUTPUT_DIR / src.name
        shutil.copy(src, dest)
        print(f"copied: {rel_path} -> {dest}")

    print(
        "\nDone. Click 'Save Version' now - these files will appear under "
        "this notebook's Output tab once the run finishes, ready to download."
    )
