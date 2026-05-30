"""Pytest conftest - fix seeds for determinism (REQ-MOD-6)."""

from __future__ import annotations

import os
import random

import numpy as np


def pytest_configure(config):  # type: ignore[no-untyped-def]
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("PYTHONHASHSEED", "42")
    random.seed(42)
    np.random.seed(42)
