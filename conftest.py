import os
import sys
from pathlib import Path

# Get the project root directory
project_root = Path(__file__).parent

# Add src directory to the beginning of sys.path
src_path = str(project_root / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path) 