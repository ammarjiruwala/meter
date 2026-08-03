# Meter backend image — the proxy, treasury, and mock provider are one process
# (uvicorn proxy.app:app), so this is a single-stage image.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root. Nothing here needs to write to the image — the ledger is Postgres and
# meter.yaml/pricing come in read-only — so the process has no reason to run as uid 0,
# and a container escape from an HTTP handler is a much duller event without it.
RUN useradd --create-home --uid 10001 meter && chown -R meter:meter /app
USER meter

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

# Shell form, and `${PORT:-8080}`, both deliberately. Render (and Cloud Run, and most
# free container hosts) assign a port at runtime through `$PORT` and route to it — an app
# hardcoded to 8080 there is reachable by nothing, and the failure looks like a health
# check timing out rather than a port mismatch. Exec form would pass the literal string
# `${PORT:-8080}` to uvicorn, so the shell has to expand it.
# Locally and in compose, nothing sets PORT and it stays 8080.
#
# `--proxy-headers` is load-bearing, not hygiene. Render terminates TLS at its edge and
# forwards, so without it every request appears to come from the edge IP — and
# `judge/sessions.py` rate-limits new sessions per IP. One shared bucket means
# MAX_SESSIONS_PER_IP_PER_HOUR stops being 8-per-judge and becomes 8-for-everyone: the
# ninth judge of the hour is refused, and the limit protects nothing it was written to
# protect. `--forwarded-allow-ips=*` is safe *here* because nothing reaches this container
# except through Render's proxy; do not carry it to a directly-exposed deployment, where
# it would let a caller spoof its own address.
CMD ["sh", "-c", "uvicorn proxy.app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
