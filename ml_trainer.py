"""
Machine learning training pipeline placeholder.

Use this module to engineer features, train models, and persist them
to the ``models/`` directory.

Example
-------

.. code-block:: bash

    python ml_trainer.py  # expects data/training_sample.csv

"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split


def load_features_labels(data_path: Path) -> Tuple[pd.DataFrame, pd.Series]:
    """Stub for loading features and labels."""

    data = pd.read_csv(data_path)
    features = data.drop(columns=["label"])
    labels = data["label"]
    return features, labels


def train_model(features: pd.DataFrame, labels: pd.Series) -> RandomForestClassifier:
    """Train a baseline RandomForest model."""

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=5,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(features, labels)
    return model


def main() -> None:
    features, labels = load_features_labels(Path("data/training_sample.csv"))
    x_train, x_valid, y_train, y_valid = train_test_split(
        features, labels, test_size=0.2, random_state=42
    )

    model = train_model(x_train, y_train)
    accuracy = model.score(x_valid, y_valid)
    print(f"Validation accuracy: {accuracy:.4f}")
    Path("models").mkdir(exist_ok=True)
    joblib.dump(model, "models/random_forest.pkl")


if __name__ == "__main__":
    main()
