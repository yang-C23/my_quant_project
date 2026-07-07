"""Small qlib 0.9.7 file-format adapter.

Qlib 0.9.7 in this environment does not ship ``scripts/dump_bin.py`` inside
the installed package. The binary format below is taken from qlib 0.9.7
``qlib.data.storage.file_storage.FileFeatureStorage.write``: a little-endian
float32 array where the first value is the calendar start index, followed by
the feature values.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_feature_bin(path: Path, values: np.ndarray, start_index: int) -> None:
    """Write one qlib day-frequency feature bin file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    np.hstack([float(start_index), values.astype("float32")]).astype("<f").tofile(path)
