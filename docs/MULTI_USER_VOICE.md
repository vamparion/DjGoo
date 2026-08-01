# Multi-user voice control

DjGoo uses one Discord bot and one playback authority per guild. Other players do not run another bot. They run **DjGoo Voice Remote**, which recognizes speech locally and submits an authenticated command envelope to the Host.

## Shared identity model

Both direct and relay pairing create the same Host-side device record:

- one Discord user;
- one Discord guild;
- one revocable device ID;
- one random device token stored by the Host only as a keyed hash;
- one requester identity used by Red Audio when the command is accepted.

Pairing codes contain eight non-ambiguous characters, expire after five minutes, and can be redeemed once. The Discord bot token never leaves the Host.

## Direct LAN pairing

1. The Host starts DjGoo and its HTTPS Voice Gateway.
2. A Discord member runs `/djgoo pair` or `!djgoo pair`.
3. DjGoo sends a one-time pairing code, gateway URL, and TLS certificate fingerprint by DM.
4. The member opens `DjGoo Voice.exe`, chooses `direct`, and enters those values.
5. The Host consumes the code and issues the device credential over certificate-pinned HTTPS.

Direct mode is appropriate when the Voice Remote can reach the Host on a trusted LAN or authenticated private overlay.

## Outbound encrypted relay pairing

1. An operator deploys the transport-only relay behind public TLS, or uses a compatible hosted relay.
2. The Host enables `voice_gateway.relay` and makes an outbound WSS connection.
3. A Discord member runs `/djgoorelay pair`.
4. DjGoo sends a one-time code, relay URL, Host room ID, Host encryption public key, and key fingerprint by DM.
5. The member opens `DjGoo Voice.exe`, chooses `relay`, and enters those values.
6. Voice Remote encrypts the pairing request to the Host's pinned X25519 public key and sends only the opaque envelope through the relay.
7. The Host decrypts the request, consumes the code, and returns the device credential through an encrypted response.

Both Host and Voice Remote make outbound connections. The Host does not expose an inbound residential port.

## Command flow

```text
microphone
   │ local audio only
   ▼
Faster-Whisper + parser
   │ structured command
   ├──────── direct: certificate-pinned HTTPS ────────┐
   │                                                  │
   └─ relay: X25519 + HKDF + ChaCha20-Poly1305 ─┐     │
                                                ▼     ▼
                                      Host command processor
                                                │
                            identity, guild, voice channel,
                            permission, timestamp, rate,
                            replay, and requester checks
                                                │
                                                ▼
                                   authoritative DjGoo queue
                                                │
                                                ▼
                                      Red Audio + Lavalink
```

Raw microphone audio remains local. The Host's direct gateway rejects raw-audio fields. Relay envelopes contain only encrypted structured data; the relay cannot decrypt the pairing code, device token, transcript, intent, query, or response.

## Relay cryptography and trust

- Host relay rooms are derived from an Ed25519 signing public key.
- Host relay registrations are signed, timestamped, nonce-bound, and replay-checked.
- Every Voice Remote request uses a fresh ephemeral X25519 key.
- HKDF-SHA256 derives request-specific encryption keys.
- ChaCha20-Poly1305 authenticates and encrypts request and response payloads.
- The Host encryption public key is fingerprint-checked before pairing.
- TLS/WSS protects routing metadata and the WebSocket session in addition to end-to-end payload encryption.

A malicious relay can delay, drop, reorder, or refuse traffic. It cannot read or forge accepted command payloads without Host/device cryptographic material. Host timestamps and command UUIDs reject stale or duplicate actions.

## Authorization

The Host checks every command, not merely the initial pairing:

- the device token is active and not revoked;
- the device belongs to the stated guild;
- the paired Discord member still exists;
- the member is currently in a voice channel;
- when DjGoo is connected, the member is in the same channel;
- destructive controls require server ownership or **Manage Server**;
- command rate limits are enforced per device;
- command UUIDs are claimed once so retries cannot duplicate playback actions;
- the Red Audio context resolves to the paired Discord member and current authorized channel.

A disconnected bot may accept only commands that can start playback and join the member's channel. Other controls are rejected until playback is active.

## Devices

Members can use:

```text
/djgoo devices
/djgoo revoke <device-id>
```

Revocation takes effect on the next request for either transport. Red's user-data deletion hook removes the user's pending pairing codes, devices, and associated command receipts.

## Relay deployment

The self-hosted relay implementation, hardened container, Caddy TLS example, and operational limits are documented in `relay/README.md`.

DjGoo does not currently operate an official hosted relay. Operating one requires a domain, infrastructure, monitoring, abuse response, privacy policy, and incident handling outside this source-code repository.

## Multiple Host processes

The Host supervisor remains single-instance on one computer. A guild must not run competing Hosts with the same Discord bot identity. One Host owns Red Audio, Lavalink, queue state, pairing state, and device authorization; Voice Remote clients and the relay are input transports only.
