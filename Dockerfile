# Single-process by design: the background scheduler (settings.scheduler_enabled)
# and the login rate limiter (app/services/rate_limiter.py) both hold
# in-process state, so this image is not meant to be scaled by adding
# uvicorn/gunicorn workers within one container — scale by running multiple
# container replicas instead, with SCHEDULER_ENABLED=true on at most one of
# them (see the README's Production deployment section for why).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/system-health').getcode()" || exit 1

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
