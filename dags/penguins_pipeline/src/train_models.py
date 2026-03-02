import pandas as pd
from airflow.providers.mysql.hooks.mysql import MySqlHook
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import joblib
import os
from penguins_pipeline.src.config import MYSQL_CONN_ID, MODELS_PATH


def train_models():
    hook = MySqlHook(mysql_conn_id=MYSQL_CONN_ID, schema="curated")
    df = hook.get_pandas_df("SELECT * FROM curated_penguins")

    X = df.drop("species", axis=1)
    y = df["species"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    models = {
        "randomforest": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                n_estimators=100, max_depth=10, random_state=42, n_jobs=-1
            )),
        ]),
        "svm": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", SVC(kernel="rbf", C=1.0, random_state=42)),
        ]),
        "gradientboosting": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", GradientBoostingClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42
            )),
        ]),
    }

    os.makedirs(MODELS_PATH, exist_ok=True)
    metrics_list = []

    for name, pipeline in models.items():
        pipeline.fit(X_train, y_train)

        y_train_pred = pipeline.predict(X_train)
        y_test_pred = pipeline.predict(X_test)

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

        joblib.dump(pipeline, os.path.join(MODELS_PATH, f"{name}_pipeline.pkl"))

    df_metrics = pd.DataFrame(metrics_list)
    joblib.dump(df_metrics, os.path.join(MODELS_PATH, "model_metrics.pkl"))
    print(df_metrics.to_string())
