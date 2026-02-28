# Reporte de Decisiones de Arquitectura — Penguins MLOps Pipeline

## Tabla de Contenidos

1. [Servicio MySQL en Docker Compose](#1-servicio-mysql-en-docker-compose)
   1. [Imagen base](#11-imagen-base)
   2. [Variables de entorno](#12-variables-de-entorno)
   3. [Puertos](#13-puertos)
   4. [Volúmenes](#14-volúmenes)
   5. [Health check](#15-health-check)
2. [Script de inicialización (`mysql-init/init.sql`)](#2-script-de-inicialización-mysql-initsql)

---

## 1. Servicio MySQL en Docker Compose

El servicio MySQL actúa como almacén de datos del pipeline de ML. Se eligió separarlo del PostgreSQL que usa Airflow internamente para mantener una separación clara de responsabilidades: PostgreSQL gestiona los metadatos de Airflow, mientras que MySQL almacena los datos del dominio (raw y curated).

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
    - ./mysql-init:/docker-entrypoint-initdb.d
  healthcheck:
    test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-padmin1234"]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 30s
```

### 1.1 Imagen base

```yaml
image: mysql:8.0
```

Se fijó la versión mayor `8.0` en lugar de usar `latest`. Esto garantiza reproducibilidad entre ambientes.

### 1.2 Variables de entorno

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

### 1.3 Puertos

```yaml
ports:
  - "3306:3306"
```

Se expone el puerto estándar de MySQL al host. 

### 1.4 Volúmenes

```yaml
volumes:
  - mysql_data:/var/lib/mysql
  - ./mysql-init:/docker-entrypoint-initdb.d
```

| Volumen | Tipo | Propósito |
|---|---|---|
| `mysql_data:/var/lib/mysql` | Named volume | Persiste los datos de MySQL entre reinicios del contenedor |
| `./mysql-init:/docker-entrypoint-initdb.d` | Bind mount | MySQL ejecuta automáticamente todos los archivos `.sql` y `.sh` dentro de `/docker-entrypoint-initdb.d` la primera vez que se inicializa la base de datos (cuando el volumen de datos está vacío). Esto permite crear las bases `raw` y `curated`, sus tablas y los permisos necesarios de forma declarativa y versionable en Git. |

### 1.5 Health check

```yaml
healthcheck:
  test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-padmin1234"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

El health check es una pieza clave para la orquestación confiable de servicios. Sin él, Docker Compose reporta el contenedor como "running" apenas el proceso arranca, pero MySQL puede tardar varios segundos en estar listo para aceptar conexiones.

| Parámetro | Valor | Justificación |
|---|---|---|
| `test` | `mysqladmin ping` | Comando ligero que verifica si el servidor acepta conexiones sin ejecutar queries pesadas. Es el método recomendado por la documentación oficial de la imagen. |
| `interval` | `10s` | Frecuencia entre chequeos. 10 segundos es un balance razonable: lo suficientemente frecuente para detectar problemas rápido, sin generar carga innecesaria. |
| `timeout` | `5s` | Tiempo máximo de espera por respuesta. Si el ping no responde en 5 segundos, se considera fallido. |
| `retries` | `5` | Número de fallos consecutivos antes de marcar el contenedor como unhealthy. Con 5 reintentos a 10s de intervalo, se toleran hasta ~50 segundos de inestabilidad antes de declarar un problema. |
| `start_period` | `30s` | Período de gracia tras el arranque del contenedor. Durante estos 30 segundos, los fallos del health check no cuentan como reintentos. Esto es importante porque MySQL necesita tiempo para inicializar el sistema de archivos InnoDB, ejecutar los scripts de `/docker-entrypoint-initdb.d` y levantar el socket de conexiones. |

Esta configuración permite que otros servicios (como los workers de Airflow) usen `depends_on` con `condition: service_healthy` para no intentar conectarse antes de que MySQL esté realmente listo.

---

## 2. Script de inicialización (`mysql-init/init.sql`)

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

Se decidió usar un script SQL de inicialización en lugar de crear las bases y tablas desde el código del DAG por las siguientes razones:

- **Idempotencia**: Todos los statements usan `IF NOT EXISTS`, por lo que el script puede ejecutarse múltiples veces sin error (aunque MySQL solo lo ejecuta en la primera inicialización del volumen).
- **Separación de responsabilidades**: La infraestructura de datos (esquemas, permisos) se define de forma declarativa y versionada, separada de la lógica del pipeline.
- **Permisos controlados**: Se otorgan privilegios al usuario `user` sobre las bases `raw` y `curated` explícitamente, y se ejecuta `FLUSH PRIVILEGES` para asegurar que los cambios tomen efecto inmediato.
- **Tabla pre-creada**: `raw.raw_penguins` se crea aquí para que el task `clear_raw` (que hace `TRUNCATE TABLE`) no falle en la primera ejecución del pipeline cuando la tabla aún no existe.
