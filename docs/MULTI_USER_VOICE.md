# Multi-user voice control

DjGoo uses one Discord bot and one playback authority per guild. Other players do not run another bot. They run **DjGoo Voice Remote**, which recognizes speech locally and submits a signed-in command envelope to the Host.

## LAN pairing

1. The Host starts DjGoo and its HTTPS Voice Gateway.
2. A Discord member runs `/djgoo pair` or `!djgoo pair`.
3. DjGoo verifies the Discord identity and sends a one-time pairing code, gateway URL, and TLS certificate fingerprint by DM.
4. The member opens `DjGoo Voice.exe` and enters those three values.
5. The Host consumes the code and issues a random device token bound to that Discord user and guild.
6. The client stores the device credential locally. The Discord bot token never leaves the Host.

Pairing codes contain eight non-ambiguous characters, expire after five minutes, and can be redeemed once. The Host stores pairing codes and device tokens as keyed hashes rather than plaintext.

## Command flow

```text
microphone
   │ local audio only
   ▼
Faster-Whisper + parser
   │ structured command over pinned TLS
   ▼
Voice Gateway
   │ identity, guild, channel, permission, rate, replay checks
   ▼
authoritative DjGoo queue
   ▼
Red Audio + Lavalink
```

The Voice Gateway rejects raw audio fields. By default, only the transcript, parsed intent, query/value fields, confidence, device identity, and a unique command ID leave the player's computer.

## Authorization

The Host checks every command, not merely the initial pairing:

- the device token is active and not revoked;
- the device belongs to the stated guild;
- the paired Discord member still exists;
- the member is currently in a voice channel;
- when DjGoo is connected, the member is in the same channel;
- destructive controls require server ownership or **Manage Server**;
- command rate limits are enforced per device;
- command UUIDs are claimed once so retries cannot duplicate playback actions.

A disconnected bot may accept only commands that can start playback and join the member's channel. Other controls are rejected until playback is active.

## Devices

Members can use:

```text
/djgoo devices
/djgoo revoke <device-id>
```

Revocation takes effect on the next request. Red's user-data deletion hook removes the user's pending pairing codes, devices, and associated command receipts.

## Network scope

The current transport is intended for a trusted LAN or a private overlay network. It binds to the configured Host address, uses TLS, and requires certificate-fingerprint pinning during pairing. It does not rely on an unprotected browser control panel.

For use outside the LAN, place both computers on an authenticated private network such as a self-managed VPN/overlay, or wait for the separately reviewed outbound relay transport. Do not expose the Voice Gateway directly to the public internet without firewall policy, abuse controls, and an explicit deployment review.

## Multiple Host processes

The existing Host supervisor remains single-instance on one computer. A guild must not run competing Hosts with the same Discord bot identity. One Host owns Red Audio, Lavalink, queue state, pairing state, and device authorization; Voice Remote clients are input devices only.
