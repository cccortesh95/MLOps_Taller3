# Penguins MLOps Pipeline — Decisiones de Arquitectura

## Tabla de Contenidos

1. [Estructura del Proyecto](#1-estructura-del-proyecto)
2. [Creación de Dockerfile custom](#2-creación-de-dockerfile-custom)
3. [Conexión a MySQL via Airflow](#3-conexión-a-mysql-via-airflow)
4. [Servicio MySQL en Docker Compose](#4-servicio-mysql-en-docker-compose)
5. [Script de inicialización de BD](#5-script-de-inicialización-de-bd)
6. [DAG: penguins_pipeline](#6-dag-penguins_pipeline)

---

## 1. Estructura del Proyecto

```
├── dags/penguins_pipeline/
│   ├── penguins_pipeline.py          # DAG principal
│   └── src/
│       ├── config.py                 # Configuración centralizada
│       ├── load_raw_penguins.py      # Carga de datos crudos
│       ├── preprocess_data.py        # Feature engineering
│       └── train_models.py           # Entrenamiento con Pipeline de sklearn
├── dataset/                          # CSV de entrada
├── docker/
│   ├── Dockerfile                    # Imagen custom de Airflow
│   ├── docker-compose.yaml           # Orquestación de servicios
│   └── pyproject.toml                # Dependencias (PEP 621)
├── models/                           # Modelos y métricas generados
├── mysql-init/
│   └── init.sql                      # Esquemas y permisos iniciales
└── plugins/
```

Infraestructura (`docker/`) separada del código del pipeline (`dags/`).

```bash
# Levantar
docker compose -f docker/docker-compose.yaml up --build

# Detener y borrar volúmenes
docker compose -f docker/docker-compose.yaml down -v
```

<!-- Imagen: Contenedores corriendo (docker ps) -->

---

## 2. Creación de Dockerfile custom

El docker-compose oficial de Airflow ofrece la variable `_PIP_ADDITIONAL_REQUIREMENTS` para instalar paquetes Python adicionales. Pero No se usó por dos razones:

1. El pipeline necesita `default-libmysqlclient-dev`, `build-essential` y `pkg-config` para compilar el cliente MySQL de Python. `_PIP_ADDITIONAL_REQUIREMENTS` solo ejecuta `pip install` y no puede instalar paquetes del sistema operativo con `apt-get`.

2. `_PIP_ADDITIONAL_REQUIREMENTS` instala las dependencias cada vez que un contenedor arranca. Con un Dockerfile custom, las dependencias se instalan una sola vez durante el build de la imagen y quedan en la cache.

Se usó uv como gestor de paquetes por su velocidad. Definimos las dependencias en `docker/pyproject.toml` y se instalan con `uv sync --no-dev`.

```dockerfile
FROM apache/airflow:2.6.0
USER root
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
         default-libmysqlclient-dev build-essential pkg-config \
  && apt-get autoremove -yqq --purge && apt-get clean \
  && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
COPY pyproject.toml /app/
WORKDIR /app
ENV UV_SYSTEM_PYTHON=1
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN uv sync --no-dev
USER airflow
```

con las variables de entorno `UV_SYSTEM_PYTHON` y `UV_PROJECT_ENVIRONMENT` evitamos que uv cree un virtualenv y fuerzan la instalación en el Python del sistema, donde Airflow busca los paquetes.

<!-- Imagen: Build exitoso del Dockerfile -->
![Docker build](images/docker_build.png)

---

## 3. Conexión a MySQL via Airflow

Los scripts usan `MySqlHook` de Airflow en vez de `mysql.connector` directo. Esto centraliza las credenciales en Airflow y las elimina del código.

La conexión se registra automáticamente via variable de entorno en el compose:

```yaml
AIRFLOW_CONN_MYSQL_DEFAULT: 'mysql://user:user1234@mysql:3306'
```

Airflow interpreta variables con prefijo `AIRFLOW_CONN_` como conexiones. Esto evita crearla manualmente en la UI cada vez que se recrean los contenedores.

---

## 4. Servicio MySQL en Docker Compose

Se creó la base de datos MySQL, con el fin de almacenar los datos del pipeline (raw y curated), de esta manera separamos del PostgreSQL que Airflow usa internamente para sus metadatos.

```yaml
mysql:
  image: mysql:8.0
  environment:
    MYSQL_ROOT_PASSWORD: admin1234
    MYSQL_DATABASE: mydatabase
    MYSQL_USER: user
    MYSQL_PASSWORD: user1234
  ports:
    - "3306:3306"
  volumes:
    - mysql_data:/var/lib/mysql
    - ../mysql-init:/docker-entrypoint-initdb.d
  healthcheck:
    test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-padmin1234"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s
```

- Versión fijada en `8.0` para reproducibilidad.
- El volumen `mysql_data` persiste datos entre reinicios.
- El volumen `mysql-init` se monta en `/docker-entrypoint-initdb.d` para ejecutar el SQL de inicialización en el primer arranque.
- Health check con `mysqladmin ping` y 30s de gracia para que MySQL termine de inicializar.

<!-- Imagen: Servicio MySQL healthy en docker ps -->
![MySQL healthy](images/mysql_healthy.png)

---

## 5. Script de inicialización de BD

El script de inicialización crea las bases `raw` y `curated`, las tablas iniciales y los permisos del usuario de servicio. Se ejecuta solo en la primera inicialización.

```sql
CREATE DATABASE IF NOT EXISTS raw;
CREATE DATABASE IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS raw.raw_penguins ( ... );
CREATE TABLE IF NOT EXISTS curated.curated_penguins ( ... );

GRANT ALL PRIVILEGES ON raw.* TO 'user'@'%';
GRANT ALL PRIVILEGES ON curated.* TO 'user'@'%';
FLUSH PRIVILEGES;
```

Las tablas se pre-crean para que los `TRUNCATE TABLE` del DAG no fallen en la primera ejecución.

<!-- Imagen: Bases de datos y tablas creadas en MySQL -->
![BD inicializada](images/bd_inicializada.png)

---

## 6. DAG: penguins_pipeline

### 6.1 Workflow

```
[clear_raw, clear_curated] >> load_raw_penguins >> preprocess_data >> train_models
```

5 tasks: los dos primeros en paralelo (limpieza), el resto secuencial.

<!-- Imagen: Graph View del DAG en Airflow -->
![DAG Graph View](images/dag_graph_view.png)

### 6.2 clear_raw / clear_curated

Con el operador `MySqlOperator` ejecutamos un `TRUNCATE TABLE` sobre ambas tablas. De esta manera se garantiza que cada ejecución parta de tablas vacías.

### 6.3 load_raw_penguins

Lee el CSV y lo inserta en `raw.raw_penguins` usando `MySqlHook`.

### 6.4 preprocess_data

Lee de `raw`, elimina `id`, calcula features derivadas y guarda en `curated.curated_penguins`:

- `bill_ratio = bill_length_mm / bill_depth_mm`
- `body_mass_kg = body_mass_g / 1000`

### 6.5 train_models

Lee de `curated`, separa features/target, hace split 80/20 y entrena 3 modelos dentro de `sklearn.pipeline.Pipeline` (StandardScaler + clasificador):

- RandomForest
- SVM
- GradientBoosting

Cada pipeline se guarda como `.pkl`. Al incluir el scaler, el modelo es autosuficiente para predicción.

### 6.6 Evidencias de ejecución

#### DAG ejecutado

<!-- Imagen: Grid/Tree View con todos los tasks en verde -->
![DAG exitoso](images/dag_exitoso.png)

#### Datos en raw.raw_penguins

<!-- Imagen: SELECT de raw.raw_penguins -->
![Datos raw](images/datos_raw.png)

#### Datos en curated.curated_penguins

<!-- Imagen: SELECT de curated.curated_penguins mostrando bill_ratio y body_mass_kg -->
![Datos curated](images/datos_curated.png)

#### Modelos generados

<!-- Imagen: ls de /opt/airflow/models/ mostrando los .pkl -->
![Modelos]()

#### Métricas

<!-- Imagen: Dataframe de métricas -->
![Métricas]()
