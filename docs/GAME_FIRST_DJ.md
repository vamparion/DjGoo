# Game-first DJ product design

DjGoo is not a general Discord bot with music commands added to it. Its primary use case is a group already inside a full-screen game. The DJ must keep music moving, accept requests, and recover from faults without requiring anyone to open logs or manage a queue manually.

## Core product rules

1. **Music should keep moving.** A temporary health miss must not kill a working bot, and a real component recovery must preserve the active station and queue.
2. **A request is not a new station.** During radio playback, `play <song>` puts one song in the request lane. The same station resumes after it.
3. **One playback authority.** Red Audio and Lavalink own the player and queue. DjGoo uses supported Red commands such as `play` and `bumpplay` rather than maintaining a second queue.
4. **Controls must work without leaving the game.** Local push-to-talk voice is the primary input. Discord buttons, chat, media keys, the Voice Remote, and a compact overlay are alternate surfaces for the same intents.
5. **Normal failures should self-heal quietly.** Raw logs are diagnostics, not the normal user interface.

## Playback model

Each guild has one playback session with three logical lanes:

```text
Now playing
    ↓
Request lane       one-off songs selected by players
    ↓
Program lane       albums and explicit playlists
    ↓
Radio lane         continuously generated station tracks
```

The lanes are logical metadata over Red's real queue, not separate players.

### Radio requests

While a station is active:

- `play Sandstorm` means **play next, then return to radio**.
- `play now Sandstorm` will mean **interrupt the current song, then return to radio**.
- `queue Sandstorm` will mean **append to the request lane without changing the next track**.
- A requested song is not automatically counted as a station recommendation.
- Skipping a requested song does not train the station negatively.
- Explicit `like`, `more like this`, `less like this`, and `ban this` actions may still train the station because the user made that choice deliberately.

Requests should retain requester identity so the deck can show who selected the track and optional fairness rules can prevent one player from monopolizing the queue.

## Reliability contract

### Startup readiness

Startup remains strict. DjGoo is not ready until:

- the packaged Lavalink process is the owned listener on port 2333;
- Red Audio is loaded and Discord is ready;
- Red-Lavalink reports at least one real `Node.ready=True` connection;
- the local voice listener is healthy when enabled.

### Runtime health

Runtime health is different from startup readiness. A single stale heartbeat is degradation, not proof that the component must be killed.

- Lavalink receives a short recovery window.
- Redbot receives a longer window for event-loop stalls, reconnects, and Windows scheduling delays.
- Voice recognition receives the longest window because model loading and audio-device changes can be slow.
- Heartbeat writers maintain a bounded lease while their owning process is alive but its async loop is busy. Redbot receives 60 seconds, the Red-Lavalink client receives 20 seconds, and the voice listener receives 90 seconds. The lease stops refreshing when the real source stops reporting, so a deadlocked or dead process still becomes stale and remains eligible for supervisor recovery.
- A saved playback snapshot or active station is treated as recovery intent. A replacement Redbot resumes the session even when the original restart request did not carry an explicit resume flag.
- Supervisor-level recovery backoff and richer degraded-state events remain a follow-up; the current change fixes the false-positive heartbeat path shown in the packaged log without masking a permanently dead process.

## In-game interaction

### Voice first

The most important response is immediate audible confirmation, not a desktop window.

Recommended earcons:

- short rising tone: command accepted;
- two-note success: request queued;
- low single tone: command rejected;
- brief spoken correction only when needed, such as “I found two versions.”

Useful commands:

```text
DjGoo, radio balanced 2000s rock
DjGoo, play Sandstorm
DjGoo, play now Sandstorm
DjGoo, skip
DjGoo, pause
DjGoo, what is playing
DjGoo, what is next
DjGoo, like this
DjGoo, don't play this again
DjGoo, lower music while we talk
```

A temporary “focus mode” should reduce volume while teammates speak and restore it afterward without pausing the station.

### Persistent Discord deck

DjGoo should maintain one message per guild and edit it instead of posting a new control message for every track.

The deck should show:

- cover art, title, artist, elapsed time, and duration;
- active station and radio mode;
- `Requested by <member>` when applicable;
- next request and the first radio track behind it;
- volume, repeat, autoplay, voice-listener, and connection status;
- buttons for pause, skip, replay, request queue, like, less like, ban, and stop.

### Compact desktop overlay

The optional overlay should be small enough to sit above a game without becoming another application to manage.

Suggested compact layout:

```text
┌──────────────────────────────────────────────┐
│ ● DJGOO   Darude — Sandstorm          02:41 │
│ REQUEST • Vamp     NEXT: Radio • Rock Hits   │
└──────────────────────────────────────────────┘
```

Requirements:

- dark charcoal background with blue and violet accents;
- 360–460 px wide, one or two rows;
- always-on-top and optional click-through mode;
- appears for a few seconds after a command or track change, then fades;
- no raw process names or logs;
- green, amber, and red health indicators only when action is needed.

### Host launcher

The main launcher is an operations surface, not the DJ deck. Its default page should contain:

- a single large Start/Stop control;
- overall state: Ready, Recovering, or Needs action;
- Now Playing and active station;
- voice-listener and paired-device status;
- update availability;
- a collapsed **Health and diagnostics** section for component details and logs.

“Lavalink,” “Redbot,” PIDs, and heartbeat ages belong under diagnostics unless they are the direct cause of a user-facing failure.

## Feature sequence

### Phase 1 — dependable continuous music

- bridge transient event-loop stalls with bounded heartbeat leases;
- preserve playback and active radio during process recovery;
- implement the radio request lane using Red `bumpplay`;
- serialize station queue top-ups to prevent duplicate recommendations;
- keep request skips out of station negative feedback.

### Phase 2 — recovery policy and complete request semantics

- supervisor-level degraded state, continuous-failure grace, and bounded recovery backoff;
- `play next`, `play now`, and `queue request` intents;
- requester attribution and per-user fairness;
- persistent request metadata across a Redbot restart;
- request-history and undo support;
- native `!play`/`!bumpplay` classification while radio is active.

### Phase 3 — no-alt-tab experience

- persistent Discord deck edited in place;
- audible command acknowledgement;
- compact desktop overlay and tray controls;
- media-key and configurable global-hotkey support;
- push-to-talk status and recognized-command toast.

### Phase 4 — smarter DJ behavior

- energy and tempo profiles for gaming, lobby, competitive, and late-night modes;
- artist and track cooldowns across stations;
- explicit-content policy per guild;
- automatic volume ducking during voice activity;
- session history, favorites, and “rebuild this session”;
- transparent recommendation explanations and station tuning controls.

## Acceptance tests

A release should not be considered stable until it passes these Windows package tests:

1. Start DjGoo, begin a station, and play for at least one hour without a false watchdog restart.
2. Queue a request during radio and verify it becomes next, plays once, and returns to the same station.
3. Skip the requested song and verify the station does not record negative feedback for it.
4. Kill Lavalink and verify Red reconnects or recovers without losing station state.
5. Kill Redbot and verify the supervisor restarts it with saved playback and station state.
6. Disconnect and restore the network without creating duplicate Java or Redbot processes.
7. Repeatedly press Start and Restart and verify process ownership remains singular and idempotent.
