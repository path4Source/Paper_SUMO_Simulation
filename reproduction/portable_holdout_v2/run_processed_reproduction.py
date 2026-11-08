"""Run the processed holdout replay from the repository entry point."""
import argparse
from pathlib import Path
import subprocess
import sys
p = argparse.ArgumentParser()
p.add_argument("--output", required=True)
a = p.parse_args()
subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).with_name("reproduce.py")), "reproduce", "--original", "--output", a.output], check=True)
