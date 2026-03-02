"""
Entrenamiento basado en train.ipynb:
- Leer datos preprocesados de curated
- Entrenar RandomForest, SVM y GradientBoosting
- Evaluar y guardar modelos y métricas
"""
import pandas as pd
from airflow.providers.mysql.hooks.mysql import MySqlHook
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import joblib
import os
from penguins_pipeline.src.config import MYSQL_CONN_ID, MODELS_PATH


def train_models():
    hook = MySqlHook(mysql_conn_id=MYSQL_CONN_ID, schema="curated")
    X_train = hook.get_pandas_df("SELECT * FROM X_train")
    X_test = hook.get_pandas_df("SELECT * FROM X_test")
    y_train = hook.get_pandas_df("SELECT * FROM y_train")["species"]
    y_test = hook.get_pandas_df("SELECT * FROM y_test")["species"]

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
