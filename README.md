# Reporte de Decisiones de Arquitectura — Penguins MLOps Pipeline

## Tabla de Contenidos

1. [Estructura del Proyecto](#1-estructura-del-proyecto)
2. [Dockerfile y Gestión de Dependencias con uv](#2-dockerfile-y-gestión-de-dependencias-con-uv)
3. [Conexión a MySQL via Airflow](#3-conexión-a-mysql-via-airflow)
4. [Servicio MySQL en Docker Compose](#4-servicio-mysql-en-docker-compose)
   1. [Imagen base](#41-imagen-base)
   2. [Variables de entorno](#42-variables-de-entorno)
   3. [Puertos](#43-puertos)
   4. [Volúmenes](#44-volúmenes)
   5. [Health check](#45-health-check)
5. [Script de inicialización (`mysql-init/init.sql`)](#5-script-de-inicialización-mysql-initsql)

---

## 1. Estructura del Proyecto

```
├── dags/
│   └── penguins_pipeline/
│       ├── penguins_pipeline.py      # DAG principal
│       └── src/
│           ├── config.py             # Configuración centralizada
│           ├── load_raw_penguins.py  # Carga de datos crudos
│           ├── preprocess_data.py    # Preprocesamiento y split
│           └── train_models.py       # Entrenamiento de modelos
├── dataset/                          # CSV de entrada
├── docker/
│   ├── Dockerfile                    # Imagen custom de Airflow
│   ├── docker-compose.yaml           # Orquestación de servicios
│   └── pyproject.toml                # Dependencias del proyecto
├── models/                           # Modelos y artefactos generados
├── mysql-init/
│   └── init.sql                      # Inicialización de MySQL
└── plugins/
```

Los archivos de Docker (`Dockerfile`, `docker-compose.yaml`, `pyproject.toml`) están agrupados en la carpeta `docker/` para mantener la configuración de infraestructura separada del código del pipeline.

Para levantar el stack:

```bash
docker compose -f docker/docker-compose.yaml up --build
```

Para detener y eliminar volúmenes:

```bash
docker compose -f docker/docker-compose.yaml down -v
```

---

## 2. Dockerfile y Gestión de Dependencias con uv

```dockerfile
FROM apache/airflow:2.6.0
USER root
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
         default-libmysqlclient-dev build-essential pkg-config \
  && apt-get autoremove -yqq --purge \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
COPY pyproject.toml /app/
WORKDIR /app
ENV UV_SYSTEM_PYTHON=1
ENV UV_PROJECT_ENVIRONMENT=/usr/local
RUN uv sync --no-dev
USER airflow
```

Se usa [uv](https://docs.astral.sh/uv/) como gestor de paquetes en lugar de pip por su velocidad de resolución e instalación de dependencias.

Las dependencias se definen en `docker/pyproject.toml`:

```toml
[project]
name = "penguins-pipeline"
version = "0.1.0"
requires-python = ">=3.7.1"
dependencies = [
    "mysql-connector-python==8.0.33",
    "pandas==1.3.5",
    "scikit-learn==1.0.2",
    "joblib==1.3.2",
    "apache-airflow-providers-mysql==5.1.0",
]
```

Decisiones clave:

| Aspecto | Decisión | Justificación |
|---|---|---|
| `uv sync --no-dev` | Instalar solo dependencias de producción | No se necesitan herramientas de desarrollo en la imagen |
| `UV_SYSTEM_PYTHON=1` | Instalar en el Python del sistema | `uv sync` por defecto crea un virtualenv; esta variable lo evita |
| `UV_PROJECT_ENVIRONMENT=/usr/local` | Apuntar al entorno del sistema | Asegura que los paquetes se instalen donde Airflow los puede encontrar |
| `pyproject.toml` en vez de `requirements.txt` | Estándar moderno de Python | Permite usar `uv add` para agregar dependencias y es compatible con PEP 621 |

Para agregar una nueva dependencia, editar `docker/pyproject.toml` y reconstruir la imagen.

---

## 3. Conexión a MySQL via Airflow

Los scripts del pipeline usan `MySqlHook` de Airflow en lugar de `mysql.connector` directo. Esto permite centralizar la configuración de conexión en Airflow y eliminar credenciales hardcodeadas del código.

```python
from airflow.providers.mysql.hooks.mysql import MySqlHook

hook = MySqlHook(mysql_conn_id="mysql_default", schema="raw")
conn = hook.get_conn()
```

La conexión `mysql_default` se registra automáticamente via variable de entorno en el `docker-compose.yaml`:

```yaml
AIRFLOW_CONN_MYSQL_DEFAULT: 'mysql://user:user1234@mysql:3306'
```

Airflow interpreta variables con el prefijo `AIRFLOW_CONN_` como definiciones de conexión. El formato es `scheme://user:password@host:port`. Esto evita tener que crear la conexión manualmente desde la UI cada vez que se recrean los contenedores.

---

## 4. Servicio MySQL en Docker Compose

El servicio MySQL actúa como almacén de datos del pipeline de ML. Se eligió separarlo del PostgreSQL que usa Airflow internamente para mantener una separación clara de responsabilidades: PostgreSQL gestiona los metadatos de Airflow, mientras que MySQL almacena los datos del dominio (raw y curated).

### 4.1 Imagen base

```yaml
image: mysql:8.0
```

Se fijó la versión mayor `8.0` en lugar de usar `latest`. Esto garantiza reproducibilidad entre ambientes.

### 4.2 Variables de entorno

```yaml
environment:
  MYSQL_ROOT_PASSWORD: admin1234
  MYSQL_DATABASE: mydatabase
  MYSQL_USER: user
  MYSQL_PASSWORD: user1234
```

| Variable | Propósito | Decisión |
|---|---|---|
| `MYSQL_ROOT_PASSWORD` | Contraseña del usuario root. Es obligatoria para que el contenedor arranque. | Se definió un valor explícito. |
| `MYSQL_DATABASE` | Crea automáticamente una base de datos al iniciar por primera vez. | Se configuró `mydatabase` como base por defecto. Las bases reales del pipeline (`raw` y `curated`) se crean en el script de inicialización para tener mayor control sobre su estructura. |
| `MYSQL_USER` | Crea un usuario no-root con permisos sobre `MYSQL_DATABASE`. | Se usa `user` como cuenta de servicio para las conexiones desde Airflow. |
| `MYSQL_PASSWORD` | Contraseña del usuario de servicio. | Mismo criterio que `MYSQL_ROOT_PASSWORD`: aceptable para desarrollo. |

### 4.3 Puertos

```yaml
ports:
  - "3306:3306"
```

Se expone el puerto estándar de MySQL al host.

### 4.4 Volúmenes

```yaml
volumes:
  - mysql_data:/var/lib/mysql
  - ../mysql-init:/docker-entrypoint-initdb.d
```

| Volumen | Tipo | Propósito |
|---|---|---|
| `mysql_data:/var/lib/mysql` | Named volume | Persiste los datos de MySQL entre reinicios del contenedor |
| `../mysql-init:/docker-entrypoint-initdb.d` | Bind mount | MySQL ejecuta automáticamente todos los archivos `.sql` y `.sh` dentro de `/docker-entrypoint-initdb.d` la primera vez que se inicializa la base de datos (cuando el volumen de datos está vacío). Esto permite crear las bases `raw` y `curated`, sus tablas y los permisos necesarios de forma declarativa y versionable en Git. |

### 4.5 Health check

```yaml
healthcheck:
  test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-padmin1234"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

| Parámetro | Valor | Justificación |
|---|---|---|
| `test` | `mysqladmin ping` | Comando ligero que verifica si el servidor acepta conexiones sin ejecutar queries pesadas. |
| `interval` | `10s` | Balance entre detección rápida y carga mínima. |
| `timeout` | `5s` | Tiempo máximo de espera por respuesta. |
| `retries` | `5` | Tolerancia de ~50 segundos de inestabilidad antes de declarar unhealthy. |
| `start_period` | `30s` | Período de gracia para que MySQL inicialice InnoDB y ejecute los scripts de init. |

---

## 5. Script de inicialización (`mysql-init/init.sql`)

```sql
CREATE DATABASE IF NOT EXISTS raw;
CREATE DATABASE IF NOT EXISTS curated;

CREATE TABLE IF NOT EXISTS raw.raw_penguins (
    id INT,
    species INT,
    island INT,
    bill_length_mm FLOAT,
    bill_depth_mm FLOAT,
    flipper_length_mm INT,
    body_mass_g INT,
    sex INT,
    year INT
);

GRANT ALL PRIVILEGES ON raw.* TO 'user'@'%';
GRANT ALL PRIVILEGES ON curated.* TO 'user'@'%';
FLUSH PRIVILEGES;
```

- **Idempotencia**: Todos los statements usan `IF NOT EXISTS`.
- **Separación de responsabilidades**: La infraestructura de datos se define de forma declarativa, separada de la lógica del pipeline.
- **Permisos controlados**: Se otorgan privilegios al usuario `user` sobre `raw` y `curated` explícitamente.
- **Tabla pre-creada**: `raw.raw_penguins` se crea aquí para que el task `clear_raw` (`TRUNCATE TABLE`) no falle en la primera ejecución.