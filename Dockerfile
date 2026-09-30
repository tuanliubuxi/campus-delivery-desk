# Production image for both the Django web process and scheduler service.
FROM python:3.12-slim

# Production defaults are explicit here; Compose may override them per service.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY pyproject.toml ./
# Install the tested transitive dependency set before copying source so ordinary
# source changes can reuse the dependency layer.
COPY requirements ./requirements
RUN pip install --no-cache-dir -r requirements/prod.lock

COPY apps ./apps
COPY config ./config
COPY templates ./templates
COPY static ./static
COPY manage.py ./

# The dependency layer above is authoritative for production image versions.
RUN pip install --no-cache-dir --no-deps .

# All persistent runtime paths live below /data and are mounted by Compose.
RUN mkdir -p /data/db /data/media /data/backups /data/tmp /data/logs

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--workers", "2", "--threads", "4", "--timeout", "60", "--bind", "0.0.0.0:8000"]
