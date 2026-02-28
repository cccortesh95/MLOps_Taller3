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
from src.config import MYSQL_CONFIG, MODELS_PATH


def preprocess_data():
    conn = mysql.connector.connect(database="raw", **MYSQL_CONFIG)
    df = pd.read_sql("SELECT * FROM raw_penguins", conn)
    conn.close()

    df_clean = df.drop("id", axis=1)

    X = df_clean.drop("species", axis=1)
    y = df_clean["species"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    scaler = StandardScaler()
    X_train_scaled = pd.DataFrame(
        scaler.fit_transform(X_train), columns=X_train.columns, index=X_train.index
    )
    X_test_scaled = pd.DataFrame(
        scaler.transform(X_test), columns=X_test.columns, index=X_test.index
    )

    os.makedirs(MODELS_PATH, exist_ok=True)
    joblib.dump(scaler, os.path.join(MODELS_PATH, "scaler.pkl"))

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
