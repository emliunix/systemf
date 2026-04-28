"""Test configuration and shared fixtures."""

import pytest
from pathlib import Path


@pytest.fixture
def test_data_dir() -> Path:
    """Returns the absolute path to the directory containing test data."""
    return Path(__file__).parent / "data"
