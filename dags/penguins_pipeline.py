from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.mysql.operators.mysql import MySqlOperator
from datetime import datetime

MYSQL_CONFIG = {
    "host": "mysql",
    "port": 3306,
    "user": "user",
    "password": "user1234",
}

DATASET_PATH = "/opt/airflow/dataset/penguins_v1.csv"
MODELS_PATH = "/opt/airflow/models"


MYSQL_CONN_ID = "mysql_default"

CLEAR_RAW_SQL = """
    TRUNCATE TABLE raw.raw_penguins;
"""

CLEAR_CURATED_SQL = """
    TRUNCATE TABLE curated.X_train;
    TRUNCATE TABLE curated.X_test;
    TRUNCATE TABLE curated.y_train;
    TRUNCATE TABLE curated.y_test;
"""


def load_raw_penguins():
    """Cargar datos crudos de penguins a raw.raw_penguins sin preprocesamiento."""
    import pandas as pd
    import mysql.connector

    df = pd.read_csv(DATASET_PATH)

    conn = mysql.connector.connect(database="raw", **MYSQL_CONFIG)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_penguins (
            id INT,
            species INT,
            island INT,
            bill_length_mm FLOAT,
            bill_depth_mm FLOAT,
            flipper_length_mm INT,
            body_mass_g INT,
            sex INT,
            year INT
        )
    """)

    for _, row in df.iterrows():
        cursor.execute(
            """INSERT INTO raw_penguins
               (id, species, island, bill_length_mm, bill_depth_mm,
                flipper_length_mm, body_mass_g, sex, year)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            tuple(row),
        )

    conn.commit()
    cursor.close()
    conn.close()


def preprocess_data():
    """
    Preprocesamiento basado en train.ipynb:
    - Leer datos de raw.raw_penguins
    - Eliminar columna 'id'
    - Separar features (X) y target (y = species)
    - Split train/test (80/20, stratify, random_state=42)
    - Escalar con StandardScaler
    - Guardar datos preprocesados en curated
    """
    import pandas as pd
    import mysql.connector
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    import joblib
    import os

    conn = mysql.connector.connect(database="raw", **MYSQL_CONFIG)
    df = pd.read_sql("SELECT * FROM raw_penguins", conn)
    conn.close()

    # Eliminar columna id
    df_clean = df.drop("id", axis=1)

    # Separar features y target
    X = df_clean.drop("species", axis=1)
    y = df_clean["species"]

    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Escalar
    scaler = StandardScaler()
    X_train_scaled = pd.DataFrame(
        scaler.fit_transform(X_train), columns=X_train.columns, index=X_train.index
    )
    X_test_scaled = pd.DataFrame(
        scaler.transform(X_test), columns=X_test.columns, index=X_test.index
    )

    # Guardar scaler
    os.makedirs(MODELS_PATH, exist_ok=True)
    joblib.dump(scaler, os.path.join(MODELS_PATH, "scaler.pkl"))

    # Guardar datos preprocesados en curated
    conn = mysql.connector.connect(database="curated", **MYSQL_CONFIG)
    cursor = conn.cursor()

    for table_name, data in [
        ("X_train", X_train_scaled),
        ("X_test", X_test_scaled),
        ("y_train", y_train.to_frame()),
        ("y_test", y_test.to_frame()),
    ]:
        cols = data.columns.tolist()
        col_defs = ", ".join([f"`{c}` FLOAT" for c in cols])
        cursor.execute(f"CREATE TABLE IF NOT EXISTS `{table_name}` ({col_defs})")
        placeholders = ", ".join(["%s"] * len(cols))
        for _, row in data.iterrows():
            cursor.execute(
                f"INSERT INTO `{table_name}` ({', '.join([f'`{c}`' for c in cols])}) VALUES ({placeholders})",
                tuple(row),
            )

    conn.commit()
    cursor.close()
    conn.close()


def train_models():
    """
    Entrenamiento basado en train.ipynb:
    - Leer datos preprocesados de curated
    - Entrenar RandomForest, SVM y GradientBoosting
    - Evaluar y guardar modelos y métricas
    """
    import pandas as pd
    import numpy as np
    import mysql.connector
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.svm import SVC
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    import joblib
    import os

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


with DAG(
    dag_id="penguins_pipeline",
    start_date=datetime(2026, 2, 28),
    schedule_interval=None,
    catchup=False,
    tags=["mlops", "penguins"],
) as dag:

    t1_raw = MySqlOperator(
        task_id="clear_raw",
        mysql_conn_id=MYSQL_CONN_ID,
        sql=CLEAR_RAW_SQL,
    )
    t1_curated = MySqlOperator(
        task_id="clear_curated",
        mysql_conn_id=MYSQL_CONN_ID,
        sql=CLEAR_CURATED_SQL,
    )
    t2 = PythonOperator(task_id="load_raw_penguins", python_callable=load_raw_penguins)
    t3 = PythonOperator(task_id="preprocess_data", python_callable=preprocess_data)
    t4 = PythonOperator(task_id="train_models", python_callable=train_models)

    [t1_raw, t1_curated] >> t2 >> t3 >> t4
