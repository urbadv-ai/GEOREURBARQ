from __future__ import annotations

import subprocess
import sys

try:
    import xlrd  # noqa: F401
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "xlrd>=2.0.1"])
