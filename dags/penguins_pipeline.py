from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.mysql.operators.mysql import MySqlOperator
from datetime import datetime

from src.load_raw_penguins import load_raw_penguins
from src.preprocess_data import preprocess_data
from src.train_models import train_models

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
