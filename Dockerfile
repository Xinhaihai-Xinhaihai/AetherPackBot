FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AETHERPACK_HOME=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md main.py ./
COPY aetherpackbot ./aetherpackbot
COPY dashboard/dist ./dashboard/dist
COPY data/config ./data/config
COPY data/dist ./data/dist

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 7619

VOLUME ["/app/data"]

CMD ["python", "main.py"]
