FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 djgoo \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin djgoo

WORKDIR /app
COPY requirements-relay.txt /app/requirements-relay.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --requirement /app/requirements-relay.txt

COPY relay /app/relay
COPY voice/__init__.py /app/voice/__init__.py
COPY voice/relay_crypto.py /app/voice/relay_crypto.py

USER 10001:10001
EXPOSE 8080

ENTRYPOINT ["python", "-m", "relay.server"]
