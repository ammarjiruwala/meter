# Meter backend image — the proxy, treasury, and mock provider are one process
# (uvicorn proxy.app:app), so this is a single-stage image.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# No volume. The ledger, wallets and treasury events used to be one SQLite file that
# had to survive a container restart; they are now in Postgres, so this image holds no
# state at all and DATABASE_URL comes in from the environment (`env_file: .env` in
# compose.yaml). That is also what makes it deployable to Fly.io, where a container has
# no durable local disk to begin with.
#
# The container will not start without DATABASE_URL — proxy/pg.py raises rather than
# silently degrading, which is the intended behaviour: a proxy with no ledger cannot
# bill anyone.

EXPOSE 8080

CMD ["uvicorn", "proxy.app:app", "--host", "0.0.0.0", "--port", "8080"]
