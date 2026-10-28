# Multi-stage Dockerfile for Azure SLA Guardian
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt greenlet

# Production Runtime
FROM python:3.12-slim

WORKDIR /app

# Non-root security user
RUN groupadd -r guardian && useradd -r -g guardian guardian

COPY --from=builder /root/.local /home/guardian/.local
COPY . .

RUN chown -R guardian:guardian /app
USER guardian

ENV PATH=/home/guardian/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "-m", "guardian.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
