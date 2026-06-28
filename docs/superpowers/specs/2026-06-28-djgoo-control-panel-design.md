# DjGoo Control Panel Design

Date: 2026-06-28

## Goal

Build a local web control panel for DjGoo that works as a hybrid control center:

- Fast enough to use during Rocket League with the fewest possible clicks.
- Deep enough to manage playlists, stations, guest requests, health, logs, and cleanup during downtime.
- Structured so a guest-safe phone mode can be shared with Discord members later.

Approved visual reference:

- `docs/mockups/djgoo-control-panel-low-clicks.html`

Earlier exploration reference:

- `docs/mockups/djgoo-control-panel-mockup.html`

## Core Product Principle

Do everything with the least amount of clicks without losing features.

Rules:

- Common game-time actions must be available from the main screen.
- Critical actions must remain visible from every screen.
- Advanced tools can be one level deeper, but not buried in multi-step menus.
- The UI should support mouse, touch, and phone use.
- Admin and guest workflows should share the same live state, but guest actions must be limited and controllable.

## User Modes

### Admin Mode

For the local DjGoo owner.

Admin can:

- See now playing, queue, station, source, and health at a glance.
- Control playback: play/pause, skip, replay, stop, volume, queue.
- Control radio: start station, stop station, like, more like, less like, ban, clean bad station memory.
- Search Nuclear and choose what to do with a result.
- Add current, previous, or searched songs to playlists.
- Repair bad playlist entries and remove duplicates.
- Restart DjGoo and inspect logs.
- Configure guest mode later.

### Guest Mode

For Discord members on phones later.

Guest can:

- See now playing.
- Search/request songs.
- Vote or request skip, depending on admin settings.
- Like/dislike current track for the active station if allowed.
- View queue.

Guest cannot:

- Restart DjGoo.
- Change system settings.
- Directly clear playlists or station memory.
- Bypass admin limits.

## Primary Layout

The approved layout has four persistent regions:

1. Top command bar
2. Left compact navigation rail
3. Main live control workspace
4. Bottom persistent critical control bar

### Top Command Bar

Purpose: one place to type or paste intent.

Examples:

- `play sandstorm`
- `radio 80s`
- `add current to chill`
- `ban this`
- `play next toxic`

Controls:

- Search/command input.
- Action selector: auto, play now, play next, add to playlist, start radio.
- Go button.
- Panic stop button.

### Left Rail

Compact labels to reduce screen space:

- Live
- Find
- Radio
- Lists
- Guests
- Logs

The rail must remain easy to tap on desktop and mobile.

### Main Live Workspace

First screen content:

- Now playing title and artist.
- Station name.
- Source/resolution status, especially Nuclear vs fallback.
- Remaining time if available.
- Queue protection status.
- One-click controls:
  - Pause/play
  - Skip
  - Like
  - More like
  - Less like
  - Ban
  - Stop radio
  - Save
  - Play next
  - Queue
  - Volume
  - Reset

### Smart Action Tiles

Visible on the live screen:

- One-tap playlist add.
- Ban and replace bad radio pick.
- Approve next guest request.
- Reset DjGoo.

These tiles should adapt over time based on common use.

### Bottom Persistent Bar

Always visible:

- Skip
- Like
- Less like
- Stop
- Current track summary

This protects game-time use when the user has navigated into another section.

## Features

### Live Controls

The live screen must show what is playing now, not only what was queued.

Controls:

- Play/pause.
- Skip.
- Replay.
- Stop.
- Volume up/down or slider.
- Queue display.
- Reset DjGoo.
- Stop radio without stopping future normal playback mode unless explicitly requested.

### Nuclear Search

Search should favor Nuclear metadata because it returns cleaner song-level results than raw YouTube search.

Search result actions:

- Play now.
- Play next.
- Add to queue.
- Start radio.
- Add to playlist.
- Ban from current station.

Search results should show:

- Title.
- Artist.
- Album if available.
- Duration.
- Source/provider.
- Confidence/quality hints where possible.

Filtering:

- Avoid long mixes, full albums, karaoke, instrumentals, clips, interviews, reactions, tutorials, playlists, and collections.
- Prefer normal song versions.

### Radio Stations

Stations and playlists are separate concepts.

Station rules:

- `radio 80s` creates or resumes `80s radio`.
- `radio 90s` creates or resumes `90s radio`.
- Likes/dislikes do not bleed between stations.
- Skipped and banned tracks should not repeat on that station.
- Less-like should steer away within that station.
- More-like and liked tracks should steer future recommendations for that station.

Station tools:

- View liked tracks.
- View more-like tracks.
- View less-like tracks.
- View banned/skipped tracks.
- Remove a mistaken rating.
- Clean bad old history.
- Rename station.
- Export/import station data.

### Playlists

Playlist tools:

- Create playlist.
- Rename playlist.
- Add current track.
- Add previous track.
- Add search result.
- Remove track.
- Reorder tracks.
- Deduplicate tracks.
- Repair bad entries.
- Shuffle/play playlist.
- Merge playlists.

Playlist names should stay simple:

- `80s`
- `chill`
- `edm`
- `rock`
- `white girl music`

### Guest Requests

Guest mode is a later phase, but the admin panel should be designed with it in mind.

Guest request controls:

- Open/close guest mode.
- Share phone link.
- View pending requests.
- Approve next request.
- Reject request.
- Trusted users.
- Request limits.
- Vote skip threshold.
- Emergency lock.

### Health And Diagnostics

The panel should help answer “why is nothing playing?” quickly.

Health checks:

- Redbot process.
- Lavalink process and connection.
- Voice listener.
- Nuclear MCP.
- Webhook target.
- Discord controls channel.
- Latest playback error.
- Latest voice recognition event.

Actions:

- Reset DjGoo.
- Start/stop voice listener.
- Open latest logs.
- Run quick diagnostics.

## Restart Behavior

Normal start:

- Clear active radio state.
- Do not resume the previous station automatically.

Reset/restart:

- Resume active radio only when launched through `Reset-DjGoo.command.ps1`.
- This is controlled with the `DJGOO_RESUME_ACTIVE_RADIO=1` environment flag.

## Architecture

Recommended implementation:

- Local web server in the DjGoo project.
- API layer that reads/writes existing DjGoo data files and sends commands through the existing command bridge.
- Frontend built as a React + Vite app for a responsive dashboard.
- Keep admin mode local/private at first.
- Add guest mode with explicit permissions later.

Initial backend responsibilities:

- Read current player state.
- Read queue state.
- Read station files.
- Read playlist files.
- Send commands to Redbot bridge.
- Query Nuclear resolver.
- Expose health status.

Initial frontend responsibilities:

- Render live dashboard.
- Trigger playback/radio/playlist actions.
- Show station memory and playlists.
- Provide low-click command bar.
- Present health and logs.

## Phases

### Phase 1: Local Admin Panel

Build:

- Web server.
- Live controls.
- Command/search bar.
- Nuclear search actions.
- Station view.
- Playlist view.
- Health view.
- Reset controls.

### Phase 2: Guest Phone Mode

Build:

- Phone-friendly guest page.
- Request queue.
- Admin approval/limits.
- Shareable LAN URL.

### Phase 3: Advanced Tuning

Build:

- Deeper radio taste editor.
- Station cleanup tools.
- Playlist repair tools.
- Export/import.
- Better diagnostics.

## Testing

Backend tests:

- Commands are routed correctly.
- Playlist edits dedupe.
- Station edits remain station-local.
- Reset-only radio resume behavior remains correct.
- Health endpoints report missing services clearly.

Frontend tests:

- Main controls are reachable from the first screen.
- Mobile layout keeps core controls visible.
- Search result actions update local UI state.
- Guest mode hides admin-only controls.

Manual verification:

- Open panel locally.
- Start a station.
- Like, less-like, skip, ban.
- Add current track to playlist.
- Reset DjGoo and verify active radio resumes only through reset.
- Normal start clears active radio.

## Non-Goals For First Pass

- Public internet hosting.
- Full Discord account authentication.
- Replacing Redbot playback.
- Replacing Nuclear as metadata resolver.
- Multi-user voice recognition.

## Open Decisions

- Exact port for local web panel.
- Whether guest mode should require a shared PIN.
- Whether the first implementation should use a lightweight Python server or a Node server.
- How much Redbot live state can be read directly versus inferred from data/logs/events.
