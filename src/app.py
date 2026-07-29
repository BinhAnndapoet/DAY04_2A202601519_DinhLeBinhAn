from pathlib import Path
import runpy
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_ROOT = REPO_ROOT / "starter_v0"
WORKBENCH_APP = WORKBENCH_ROOT / "app.py"

if not WORKBENCH_APP.is_file():
    raise FileNotFoundError(f"Workbench entry point not found: {WORKBENCH_APP}")

sys.path.insert(0, str(WORKBENCH_ROOT))
runpy.run_path(str(WORKBENCH_APP), run_name="__main__")
