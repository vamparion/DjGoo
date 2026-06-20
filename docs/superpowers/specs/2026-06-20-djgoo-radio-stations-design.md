# DjGoo Radio Stations Design

## Goal

DjGoo should support smart, dynamic radio stations that are separate from saved playlists. A playlist is a user-curated list of tracks. A station is a saved taste profile seeded by a song or phrase and continuously improved by station-specific feedback.

The first station command is:

```text
DjGoo radio Sandstorm
```

That command creates or resumes a saved station named `Sandstorm radio`, starts from the seed `Sandstorm`, and then keeps playing similar music without repeating the same obvious order.

## User Experience

`DjGoo play Sandstorm` keeps its current direct playback behavior.

`DjGoo radio Sandstorm` starts radio mode. If the station already exists, DjGoo resumes that station's memory. If it does not exist, DjGoo creates it.

While a station is active, these curation commands are available:

```text
DjGoo like this
DjGoo more like this
DjGoo less like this
DjGoo don't play this again
DjGoo station status
```

`DjGoo skip` continues to skip the current song. In radio mode it also counts as a light negative signal for the active station, but it does not ban the song.

## Overlay Behavior

When a radio song starts, DjGoo posts a visual-only Discord overlay embed. It must not mention users, trigger sound intentionally, or send extra noisy text outside the embed.

The radio song overlay includes:

- Song title and artist if available.
- Station name, such as `Sandstorm radio`.
- A short reason, such as `Seed match`, `Because you liked ...`, or `Fresh similar pick`.
- A subtle reminder footer:

```text
DjGoo like this | more like this | less like this | don't play this again
```

The overlay should be useful during a fast game: short, glanceable, and not chatty.

## Station Storage

Stations are stored separately from playlists at:

```text
data/djgoo-stations.json
```

Each station keeps its own memory so preferences never bleed across stations:

- `name`: station display name, such as `Sandstorm radio`.
- `seed`: original seed, such as `Sandstorm`.
- `created_at` and `updated_at`.
- `played`: tracks already played by this station.
- `recent`: a shorter anti-repeat window.
- `liked`: tracks explicitly liked in this station.
- `banned`: tracks that must not play again in this station.
- `more_like`: anchor tracks that should pull future choices closer.
- `less_like`: anchor tracks that future choices should drift away from.
- `last_track`: the most recent station track.

Tracks are identified primarily by URI when available, falling back to normalized title.

## Candidate Selection

The first implementation uses free local/Redbot-compatible sources:

1. Build search phrases from the seed and station memory.
2. Use Red Audio/Lavalink playback/search through the existing bridge where possible.
3. Maintain a candidate pool in station memory.
4. Filter out banned tracks and recent repeats.
5. Score candidates higher if they relate to liked or `more_like` anchors.
6. Score candidates lower if they relate to `less_like` anchors or recent skips.
7. Randomly choose among the top candidates rather than always taking the top result.

This randomness is intentional. A station should feel coherent but not predictable.

## Playback Flow

When `DjGoo radio <seed>` runs:

1. Normalize the seed and station name to `<seed> radio`.
2. Create or load the station.
3. Mark it as the active station for the current Discord guild.
4. Queue or play the seed track first unless it is banned.
5. Generate and queue the next station pick.
6. On each track transition, continue topping up the station queue.

If the system cannot confidently find a next track, it posts a quiet overlay asking for a better seed or curation, then tries a broader seed-based search.

## Command Handling

The voice parser adds these intents:

- `start_radio` with `query`.
- `station_like_current`.
- `station_more_like_current`.
- `station_less_like_current`.
- `station_ban_current`.
- `station_status`.

The Red-side audio bridge handles these intents and updates `data/djgoo-stations.json`.

## Error Handling

If no one is in voice, DjGoo posts a quiet overlay asking someone to join voice.

If no station is active and a curation command is used, DjGoo posts a quiet overlay saying there is no active station.

If the current song cannot be identified, DjGoo posts a quiet overlay saying it could not read the current track.

If candidate generation finds only banned or repeated songs, DjGoo broadens the search from liked anchors back to the original seed.

## Testing

Unit tests cover:

- Station name normalization.
- Creating/resuming `<seed> radio`.
- Station memory isolation.
- Banned tracks never being selected.
- Recent tracks being avoided.
- Likes and more/less anchors updating only the active station.
- Parser support for all station voice commands.
- Overlay payload shape for station song cards.

Runtime verification covers:

- Red loads `audio` and `djgoowelcome`.
- Voice listener starts.
- Synthetic queue item for `start_radio` drains.
- Station storage file updates.

## Out Of Scope For First Pass

No paid APIs are required.

No spoken responses are added.

No cross-station preference sharing is added.

No advanced audio fingerprinting or ML embeddings are required for the first version.
