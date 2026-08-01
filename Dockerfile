# Meter backend image — the proxy, treasury, and mock provider are one process
# (uvicorn proxy.app:app), so this is a single-stage image with a volume for the
# SQLite ledger.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The ledger, wallets, and treasury events all live in one SQLite file; keep it on
# a volume so a container restart doesn't wipe the demo's spend history.
VOLUME /data
ENV METER_DB_PATH=/data/meter.db

EXPOSE 8080

CMD ["uvicorn", "proxy.app:app", "--host", "0.0.0.0", "--port", "8080"]
