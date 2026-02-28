"""
Entrenamiento basado en train.ipynb:
- Leer datos preprocesados de curated
- Entrenar RandomForest, SVM y GradientBoosting
- Evaluar y guardar modelos y métricas
"""
import pandas as pd
import mysql.connector
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import joblib
import os
from src.config import MYSQL_CONFIG, MODELS_PATH


def train_models():
    conn = mysql.connector.connect(database="curated", **MYSQL_CONFIG)
    X_train = pd.read_sql("SELECT * FROM X_train", conn)
    X_test = pd.read_sql("SELECT * FROM X_test", conn)
    y_train = pd.read_sql("SELECT * FROM y_train", conn)["species"]
    y_test = pd.read_sql("SELECT * FROM y_test", conn)["species"]
    conn.close()

    models = {
        "randomforest": RandomForestClassifier(
            n_estimators=100, max_depth=10, random_state=42, n_jobs=-1
        ),
        "svm": SVC(kernel="rbf", C=1.0, random_state=42),
        "gradientboosting": GradientBoostingClassifier(
            n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42
        ),
    }

    os.makedirs(MODELS_PATH, exist_ok=True)
    metrics_list = []

    for name, model in models.items():
        model.fit(X_train, y_train)

        y_train_pred = model.predict(X_train)
        y_test_pred = model.predict(X_test)

        metrics_list.append(
            {
                "model": name,
                "train_accuracy": accuracy_score(y_train, y_train_pred),
                "test_accuracy": accuracy_score(y_test, y_test_pred),
                "test_precision": precision_score(y_test, y_test_pred, average="weighted"),
                "test_recall": recall_score(y_test, y_test_pred, average="weighted"),
                "test_f1": f1_score(y_test, y_test_pred, average="weighted"),
            }
        )

        joblib.dump(model, os.path.join(MODELS_PATH, f"{name}_model.pkl"))

    df_metrics = pd.DataFrame(metrics_list)
    joblib.dump(df_metrics, os.path.join(MODELS_PATH, "model_metrics.pkl"))
    print(df_metrics.to_string())
