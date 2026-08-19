FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
COPY alembic ./alembic
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/backend
EXPOSE 8000

