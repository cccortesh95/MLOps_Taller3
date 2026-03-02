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
