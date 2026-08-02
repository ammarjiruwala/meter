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

# Shell form on purpose, so `$PORT` expands at runtime.
#
# Fly reads the port from fly.toml and leaves PORT unset, so the 8080 default applies
# and nothing changes there. Render, Railway and Cloud Run all inject PORT and health-
# check *that* port — with the exec form's hardcoded 8080 the container starts happily,
# never answers on the port being probed, and is killed as unhealthy. The failure looks
# like a broken app rather than a port mismatch.
CMD uvicorn proxy.app:app --host 0.0.0.0 --port ${PORT:-8080}
