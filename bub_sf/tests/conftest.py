"""Pytest configuration for bub_sf tests."""

import sys
from pathlib import Path

# Add src directory to Python path so 'bub_sf' can be imported
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))
