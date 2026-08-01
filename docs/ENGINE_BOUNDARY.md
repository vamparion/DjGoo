# DjGoo product and engine boundary

DjGoo presents one product vocabulary to players, recipients, and Host operators:

- **DjGoo Control Center** — Host application and session controls
- **DjGoo Music Core** — Discord playback and queue services
- **DjGoo Audio Engine** — local audio-node process
- **DjGoo Voice** — recipient controller and local speech recognition
- **DjGoo Link** — authenticated direct or encrypted relay connection
- **DjGoo Mini Player** — compact always-on-top game control surface

Third-party implementation names do not belong in ordinary setup, status, playback, or recipient screens. They remain available in advanced diagnostics, manifests, source code, licenses, and support bundles where accurate dependency identification matters.

## Why DjGoo does not rewrite the complete music engine yet

DjGoo currently uses Red-DiscordBot Audio and Lavalink as internal GPL-compatible components. Replacing them immediately would require DjGoo to independently maintain Discord voice connection handling, media loading, queue semantics, permissions, reconnect behavior, codecs, filters, source plugins, and every Discord API compatibility change.

That rewrite would not improve the player experience by itself. It would replace a working alpha.11 playback contract with a new and largely untested engine. DjGoo therefore uses an adapter boundary:

```text
voice / buttons / recipient / overlay
                 │
                 ▼
          DjGoo intent layer
                 │
                 ▼
         DjGoo Music Core API
                 │
                 ▼
      internal playback dependencies
```

The intent layer owns product behavior: request lanes, radio continuation, requester attribution, station learning, persistent controls, recovery, pairing, and command discovery. The internal engine owns low-level playback.

## Rules

1. No user-facing screen requires knowledge of an internal dependency name.
2. DjGoo remains the only product and configuration surface.
3. Internal engine APIs are called through narrow bridge modules.
4. Playback state remains authoritative in one queue per Discord server.
5. Legal notices and source attribution remain complete and unmodified.
6. A future native engine must pass the same behavioral and recovery contract before replacing the current implementation.

## Native-engine exit criteria

A DjGoo-native replacement becomes reasonable only when it can prove all of the following on Windows packages:

- one-hour radio and request soak without queue drift;
- Discord reconnect without losing the active station or request class;
- exact request-next and request-now semantics;
- permission and requester checks equivalent to the current Music Core;
- source resolution and playback quality equal to or better than alpha.11;
- automated migration and rollback;
- no increase in setup requirements for Host or recipient users.

Until then, encapsulation is the safer engineering choice.
