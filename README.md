# Penguins MLOps Pipeline — Decisiones de Arquitectura

## Tabla de Contenidos

1. [Estructura del Proyecto](#1-estructura-del-proyecto)
2. [Creación de Dockerfile custom](#2-creación-de-dockerfile-custom)
3. [Conexión a MySQL via Airflow](#3-conexión-a-mysql-via-airflow)
4. [Servicio MySQL en Docker Compose](#4-servicio-mysql-en-docker-compose)
5. [Script de inicialización de BD](#5-script-de-inicialización-de-bd)
6. [DAG: penguins_pipeline](#6-dag-penguins_pipeline)
7. [Volumen compartido de modelos](#7-volumen-compartido-de-modelos)
8. [API de predicción](#8-api-de-predicción)

---

## 1. Estructura del Proyecto

```
├── api/                              # API de predicción (FastAPI)
│   ├── app.py                        # Endpoints
│   └── utils/
│       ├── logger.py                 # Logger de predicciones
│       └── model_utils.py            # Carga y descubrimiento de modelos
├── dags/penguins_pipeline/
│   ├── penguins_pipeline.py          # DAG principal
│   └── src/
│       ├── config.py                 # Configuración centralizada
│       ├── load_raw_penguins.py      # Carga de datos crudos
│       ├── preprocess_data.py        # Feature engineering
│       └── train_models.py           # Entrenamiento con Pipeline de sklearn
├── dataset/                          # CSV de entrada
├── docker/
│   ├── airflow/
│   │   ├── Dockerfile                # Imagen custom de Airflow
│   │   └── pyproject.toml            # Dependencias de Airflow
│   ├── api/
│   │   ├── Dockerfile                # Imagen de la API
│   │   └── pyproject.toml            # Dependencias de la API
│   └── docker-compose.yaml           # Orquestación de servicios
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

Se usó uv como gestor de paquetes por su velocidad. Definimos las dependencias en `docker/airflow/pyproject.toml` y se instalan con `uv sync --no-dev`.

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

---

## 7. Volumen compartido de modelos

El DAG genera los modelos `.pkl` en Airflow y la API necesita leerlos para servir predicciones. Para compartir estos archivos entre ambos servicios se usa un named volume de Docker llamado `models_data`.

```yaml
volumes:
  models_data:
```

Se monta en dos rutas distintas según el servicio:

| Servicio | Ruta de montaje | Uso |
|----------|----------------|-----|
| Airflow (worker, scheduler, etc.) | `/opt/airflow/models` | Escritura de `.pkl` |
| penguin-api | `/app/models` | Lectura de `.pkl` |

### 7.1 Permisos de escritura

Docker crea los named volumes con propietario `root`, pero los servicios de Airflow corren como usuario `50000:0`. Para que el task `train_models` pueda escribir en el volumen, el servicio `airflow-init` (que corre como root) ajusta los permisos durante la inicialización.

Se montó el volumen explícitamente en `airflow-init` porque este servicio sobreescribe los volumes heredados de `x-airflow-common`:

```yaml
airflow-init:
  volumes:
    - ${AIRFLOW_PROJ_DIR:-..}:/sources
    - models_data:/opt/airflow/models
```

Y en el script de inicialización se cambia el propietario y los permisos:

```bash
chown -R "${AIRFLOW_UID}:0" /opt/airflow/models
chmod -R 775 /opt/airflow/models
```

---

## 8. API de predicción

### 8.1 Integración en Docker Compose

La API se agregó como servicio `penguin-api` en el compose. Comparte un volumen `models_data` con Airflow para acceder a los modelos generados por el pipeline:

```yaml
penguin-api:
  build:
    context: ..
    dockerfile: docker/api/Dockerfile
  ports:
    - "8989:8000"
  volumes:
    - models_data:/app/models
  environment:
    MODELS_DIR: /app/models
  healthcheck:
    test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 15s
  restart: always
```

El volumen `models_data` se monta en `/opt/airflow/models` para Airflow (donde el DAG escribe los `.pkl`) y en `/app/models` para la API, donde los lee para servir predicciones.

Al usar un named volume, Docker lo crea como root. Para que el usuario `airflow` (UID 50000) pueda escribir los modelos, se agregó un `chown` en el servicio `airflow-init`:

```bash
chown -R "${AIRFLOW_UID}:0" /opt/airflow/models
```

La API corre internamente en el puerto 8000 y se expone en el puerto 8989 del host.

<!-- Imagen: Servicio penguin-api corriendo -->
![API corriendo]()

### 8.2 Dockerfile de la API

La imagen usa Python 3.9 con uv para instalar las dependencias desde `docker/api/pyproject.toml`. Se copian los fuentes de `api/` al contenedor.

### 8.3 Endpoints

#### GET /health

Endpoint de health check que retorna `{"status": "ok"}`. Se creó para que Docker Compose pueda verificar que la API está lista y respondiendo. El healthcheck del compose hace una petición a este endpoint cada 30 segundos usando `urllib` de Python (la imagen slim no incluye curl).

#### GET /models

Lista los modelos disponibles dinámicamente escaneando el directorio de modelos. Retorna nombre, endpoint de clasificación y métricas de cada modelo.

#### POST /classify/{model_name}

Recibe las features de un pingüino, calcula las features derivadas (`bill_ratio`, `body_mass_kg`), ejecuta la predicción con el modelo solicitado y retorna la especie.

### 8.4 Evidencias

#### API respondiendo

<!-- Imagen: Respuesta de GET /health o /models -->
![API health]()

#### Predicción exitosa

<!-- Imagen: Respuesta de POST /classify con un modelo -->
![Predicción]()

#### Swagger UI

La documentación interactiva está disponible en `http://localhost:8989/docs`.

<!-- Imagen: Swagger UI de la API -->
![Swagger]()

