"""Where the app's files live. From source, that's this folder. Packaged, it's the folder holding Ultron.exe,
because the program sits in an internal folder the exe unpacks to, while the base model, the adapters and the
HUD's small state files sit next to the exe, where they can be replaced without rebuilding it."""
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).parent
