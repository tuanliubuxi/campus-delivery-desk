FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY pyproject.toml ./
COPY apps ./apps
COPY config ./config
COPY templates ./templates
COPY static ./static
COPY manage.py ./

RUN pip install --no-cache-dir .

RUN mkdir -p /data/db /data/media /data/backups /data/tmp /data/logs

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--workers", "2", "--threads", "4", "--timeout", "60", "--bind", "0.0.0.0:8000"]
