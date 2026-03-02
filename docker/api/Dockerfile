FROM python:3.9-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY docker/api/pyproject.toml .
RUN uv sync --no-dev

COPY api/ /app/

RUN mkdir -p /app/models /app/results

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
