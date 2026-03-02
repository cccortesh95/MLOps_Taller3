"""Cargar datos crudos de penguins a raw.raw_penguins sin preprocesamiento."""
import pandas as pd
from airflow.providers.mysql.hooks.mysql import MySqlHook
from src.config import MYSQL_CONN_ID, DATASET_PATH


def load_raw_penguins():
    df = pd.read_csv(DATASET_PATH)

    hook = MySqlHook(mysql_conn_id=MYSQL_CONN_ID, schema="raw")
    conn = hook.get_conn()
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
