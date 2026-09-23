# Hosted DjGoo Relay

The hosted relay is the preferred internet transport for DjGoo Voice and the web player. It forwards opaque end-to-end encrypted envelopes between a Host and its paired clients. The relay does not receive the Discord bot token, device token plaintext, playback authority, or decrypted commands.

## Recommended public deployment

Use one project-operated relay for many DjGoo installations. Individual DjGoo users should not need to deploy their own tunnel or relay.

Requirements:

- a Linux server or VM with Docker Compose;
- a DNS name such as `relay.example.com` pointing to that server;
- inbound TCP ports 80 and 443. UDP 443 is optional but recommended for HTTP/3.

From the repository root:

```bash
export DJGOO_RELAY_DOMAIN=relay.example.com
docker compose -f relay/compose.yml up -d --build
```

Caddy obtains and renews the public TLS certificate automatically. The relay container is not published directly; only Caddy can reach its port 8080, so `DJGOO_RELAY_TRUST_PROXY=1` is safe in this layout.

Verify it:

```bash
curl https://relay.example.com/healthz
```

The response should report `"service": "djgoo-relay"` and `"status": "ok"`.

## Configure a DjGoo Host

Set the Host's relay URL in `config/secrets.json`:

```json
{
  "voice_gateway": {
    "relay": {
      "enabled": true,
      "url": "wss://relay.example.com"
    }
  }
}
```

Preserve the rest of the existing file. Restart DjGoo after changing the relay setting.

When the Host is connected, `/djgoo web` can include the hosted relay route. Browsers prefer it and retain Discord's encrypted webhook route as a fallback when one is available. Existing paired browser credentials can adopt a new relay route from a fresh `/djgoo web` link without being erased or paired again.

## Scaling model

A single relay process is intentionally stateless with respect to decrypted DjGoo data and keeps only active socket routing in memory. It is suitable for the first public deployment and can handle many concurrent rooms without creating a process per Discord server.

Do not run multiple relay replicas behind a normal round-robin load balancer yet. Active Host and client routes are process-local, so different replicas cannot currently exchange a request. Horizontal scaling requires room-aware routing or a shared broker such as Redis/NATS. Until that is implemented, scale a single relay instance vertically and monitor `/healthz`, connection counts, CPU, memory, open-file limits, and network throughput.

## Security notes

- Keep TLS termination enabled. Do not set `DJGOO_RELAY_ALLOW_INSECURE=1` on a public deployment.
- Set `DJGOO_RELAY_TRUST_PROXY=1` only when direct access to the relay container is blocked and requests arrive through a trusted reverse proxy.
- Do not log WebSocket payloads. They are encrypted, but metadata minimization still matters.
- Do not expose the Host's local gateway ports to the public internet.
- Relay compromise must not grant playback authority; Host-side device authentication, guild checks, permissions, replay protection, and rate limits remain authoritative.
