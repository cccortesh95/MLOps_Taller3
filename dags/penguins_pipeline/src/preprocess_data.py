import pandas as pd
from airflow.providers.mysql.hooks.mysql import MySqlHook
from penguins_pipeline.src.config import MYSQL_CONN_ID


def preprocess_data():
    raw_hook = MySqlHook(mysql_conn_id=MYSQL_CONN_ID, schema="raw")
    df = raw_hook.get_pandas_df("SELECT * FROM raw_penguins")

    df = df.drop("id", axis=1)

    df["bill_ratio"] = df["bill_length_mm"] / df["bill_depth_mm"]
    df["body_mass_kg"] = df["body_mass_g"] / 1000

    curated_hook = MySqlHook(mysql_conn_id=MYSQL_CONN_ID, schema="curated")
    conn = curated_hook.get_conn()
    cursor = conn.cursor()

    cols = df.columns.tolist()
    col_defs = ", ".join([f"`{c}` FLOAT" for c in cols])
    cursor.execute(f"CREATE TABLE IF NOT EXISTS `curated_penguins` ({col_defs})")

    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join([f"`{c}`" for c in cols])
    for _, row in df.iterrows():
        cursor.execute(
            f"INSERT INTO `curated_penguins` ({col_names}) VALUES ({placeholders})",
            tuple(row),
        )

    conn.commit()
    cursor.close()
    conn.close()
