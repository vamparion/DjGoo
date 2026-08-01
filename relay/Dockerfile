FROM python:3.11-slim@sha256:4b8c2a4c8f6c4f9bc90d2ee173cb447cb32c8086500cf45a7e61a5cfb4c4638a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DJGOO_RELAY_HOST=0.0.0.0 \
    DJGOO_RELAY_PORT=8080

WORKDIR /app

RUN addgroup --system --gid 10001 djgoo \
    && adduser --system --uid 10001 --ingroup djgoo --home /nonexistent --no-create-home djgoo

COPY requirements-relay.txt /app/requirements-relay.txt
RUN python -m pip install --no-cache-dir --requirement /app/requirements-relay.txt

COPY LICENSE THIRD_PARTY_NOTICES.md /app/
COPY relay /app/relay
COPY voice/__init__.py voice/relay_crypto.py /app/voice/

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)); assert data['status']=='ok'"

ENTRYPOINT ["python", "-m", "relay.server"]
