# DjGoo Relay

DjGoo Relay is a transport-only WebSocket router for Voice Remote clients that cannot reach a Host directly. Both Host and Voice Remote make outbound connections, so the Host does not require router port forwarding.

The relay does not receive a Discord bot token, device token, pairing code, transcript, command intent, query, or microphone audio in readable form. It sees only the Host room identifier, temporary route identifiers, timing, connection metadata, and end-to-end encrypted envelopes.

## Security model

- Host rooms are derived from an Ed25519 signing public key.
- Every Host connection starts with a signed, timestamped, nonce-bound registration message.
- Replayed or tampered Host registrations are rejected.
- Voice Remote requests use an ephemeral X25519 key exchange with the Host's pinned public key.
- HKDF-SHA256 derives per-request keys.
- ChaCha20-Poly1305 authenticates and encrypts request and response payloads.
- The relay cannot impersonate a Host without the Host signing and encryption private keys.
- The relay process stores no command or credential database.
- TLS/WSS remains mandatory to protect routing metadata and resist network manipulation.

This design limits what a compromised relay can read. A malicious relay can still delay, drop, reorder, or refuse traffic. Command UUID replay protection and timestamps at the Host prevent duplicated or stale playback actions.

## Deploy with Docker Compose

Requirements:

- a Linux server or VPS with Docker Compose;
- a DNS name pointing to that server;
- inbound TCP 80/443 and UDP 443 for Caddy certificate issuance and HTTP/3;
- no persistent relay application database.

```bash
cd relay
cp docker-compose.example.yml docker-compose.yml
export RELAY_DOMAIN=relay.example.com
docker compose up -d --build
```

Caddy obtains and renews the public TLS certificate. The relay container is unprivileged, read-only, has all Linux capabilities dropped, and is reachable only through Caddy.

Verify:

```bash
curl https://relay.example.com/healthz
```

Expected response:

```json
{
  "service": "djgoo-relay",
  "status": "ok",
  "protocol": 1
}
```

## Configure a Host

In `config/secrets.json`:

```json
{
  "voice_gateway": {
    "relay": {
      "enabled": true,
      "url": "wss://relay.example.com/"
    }
  }
}
```

Restart DjGoo. An administrator can check the non-secret room and key fingerprint with:

```text
/djgoorelay status
```

A user creates an encrypted internet pairing bundle with:

```text
/djgoorelay pair
```

The user enters the DM values in `DjGoo Voice.exe` after choosing the `relay` connection mode.

## Development mode

Plain `ws://` is prohibited in normal clients and Hosts. The server alone can permit local cleartext testing with:

```bash
DJGOO_RELAY_ALLOW_INSECURE=1 python -m relay.server --host 127.0.0.1 --port 8080
```

Do not use that setting on a public network.

## Operational limits

The relay is intentionally minimal. Production operators should also provide:

- upstream connection and request rate limiting;
- DDoS protection appropriate to expected usage;
- monitored TLS certificate renewal;
- container image updates and vulnerability scanning;
- privacy-preserving retention limits for reverse-proxy connection logs;
- geographically appropriate privacy and abuse policies.

DjGoo does not currently operate an official hosted relay. This directory provides the deployable self-hosted implementation; operating a public service requires infrastructure, a domain, monitoring, incident response, and a published privacy policy.
