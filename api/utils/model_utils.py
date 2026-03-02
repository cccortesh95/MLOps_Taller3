import os
import glob

import joblib
import pandas as pd


MODELS_DIR = os.environ.get("MODELS_DIR", "/app/models")
METRICS_PATH = os.path.join(MODELS_DIR, "model_metrics.pkl")
SPECIES_MAP = {1: "Adelie", 2: "Chinstrap", 3: "Gentoo"}


def load_metrics():
    """Carga métricas si el archivo existe."""
    if os.path.exists(METRICS_PATH):
        df = joblib.load(METRICS_PATH)
        return {
            row["model"].lower(): {
                "train_accuracy": row["train_accuracy"],
                "test_accuracy": row["test_accuracy"],
                "test_precision": row["test_precision"],
                "test_recall": row["test_recall"],
                "test_f1": row["test_f1"],
            }
            for _, row in df.iterrows()
        }
    return {}


def discover_models():
    """Descubre dinámicamente los modelos .pkl disponibles."""
    models = {}
    for pattern in ["*_pipeline.pkl", "*_model.pkl"]:
        for path in glob.glob(os.path.join(MODELS_DIR, pattern)):
            filename = os.path.basename(path)
            name = filename.replace("_pipeline.pkl", "").replace("_model.pkl", "").lower()
            if name not in models:
                models[name] = path
    return models


def load_model(path):
    """Carga un modelo desde disco."""
    return joblib.load(path)


def is_pipeline(model):
    """Detecta si el modelo cargado es un Pipeline de sklearn."""
    return hasattr(model, "steps")
