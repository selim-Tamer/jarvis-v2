"""Streamlit entry point; shared UI lives in cloud.ui for reliable page reloads."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cloud.ui import main

if __name__ == "__main__":
    main()
