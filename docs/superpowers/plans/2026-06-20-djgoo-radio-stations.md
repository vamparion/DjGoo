# DjGoo Radio Stations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add saved, station-specific radio mode where `DjGoo radio Sandstorm` creates/resumes `Sandstorm radio`, avoids repeats, and learns from station-local curation commands.

**Architecture:** Keep playlists and stations separate. Add a pure-Python station store under `voice/`, extend the voice parser with station intents, and integrate radio behavior into the existing Red-side `DjGooAudioBridge`. Radio uses Red Audio for playback and a JSON station memory file for seed, played history, likes, bans, anchors, and active station state.

**Tech Stack:** Python 3.11, Red-DiscordBot, Lavalink/Red Audio, `unittest`, JSON storage.

---

## File Structure

- Create `voice/djgoo_stations.py`: pure station storage, normalization, anti-repeat candidate selection, station updates.
- Create `tests/test_djgoo_stations.py`: unit tests for station identity, isolation, bans, recent avoidance, curation updates.
- Modify `voice/command_parser.py`: parse `radio`, `like this`, `more like this`, `less like this`, `don't play this again`, and `station status`.
- Modify `tests/test_voice_command_parser.py`: parser coverage for station commands.
- Modify `voice/command_queue.py`: no behavior change expected unless queue item shape needs `station`; keep generic command fields.
- Modify `local_cogs/djgoowelcome/helpers.py`: add station overlay payload builder.
- Modify `tests/test_djgoowelcome_helpers.py`: overlay payload tests.
- Modify `local_cogs/djgoowelcome/audio_bridge.py`: station playback, curation handling, station status, queue top-up.
- Modify `README.md`: document radio commands and station storage.

---

### Task 1: Station Store

**Files:**
- Create: `voice/djgoo_stations.py`
- Test: `tests/test_djgoo_stations.py`

- [x] **Step 1: Write failing station store tests**

Create `tests/test_djgoo_stations.py`:

```python
import tempfile
import unittest
from pathlib import Path

from voice.djgoo_stations import DjGooStations, normalize_station_seed, track_key


class DjGooStationsTests(unittest.TestCase):
    def test_radio_seed_creates_stable_station_name(self):
        self.assertEqual(normalize_station_seed("  Sandstorm  "), "sandstorm")
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            station = stations.get_or_create("Sandstorm")
            resumed = stations.get_or_create("sandstorm")

            self.assertEqual(station["name"], "Sandstorm radio")
            self.assertEqual(resumed["id"], station["id"])
            self.assertEqual(resumed["seed"], "Sandstorm")

    def test_station_memories_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            stations.add_feedback("Sandstorm", "liked", {"title": "A", "uri": "u:a"})
            stations.add_feedback("Chill", "liked", {"title": "B", "uri": "u:b"})

            self.assertEqual(stations.get_station("Sandstorm")["liked"][0]["title"], "A")
            self.assertEqual(stations.get_station("Chill")["liked"][0]["title"], "B")

    def test_banned_and_recent_tracks_are_not_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stations = DjGooStations(Path(temp_dir) / "stations.json")
            stations.get_or_create("Sandstorm")
            stations.add_feedback("Sandstorm", "banned", {"title": "Bad", "uri": "u:bad"})
            stations.mark_played("Sandstorm", {"title": "Recent", "uri": "u:recent"})

            candidates = [
                {"title": "Bad", "uri": "u:bad"},
                {"title": "Recent", "uri": "u:recent"},
                {"title": "Fresh", "uri": "u:fresh"},
            ]

            picked = stations.pick_candidate("Sandstorm", candidates, rng_seed=1)

            self.assertEqual(picked["title"], "Fresh")

    def test_track_key_prefers_uri_and_falls_back_to_title(self):
        self.assertEqual(track_key({"title": "Song", "uri": "https://x"}), "uri:https://x")
        self.assertEqual(track_key({"title": "Song", "uri": ""}), "title:song")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run:

```powershell
$env:PYTHONPATH='C:\Users\VERA\Documents\DiscordBot'
.\.voice-venv\Scripts\python.exe -m unittest tests.test_djgoo_stations -v
```

Expected: fails with `ModuleNotFoundError: No module named 'voice.djgoo_stations'`.

- [x] **Step 3: Implement station store**

Create `voice/djgoo_stations.py` with:

```python
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


RECENT_LIMIT = 50


def normalize_station_seed(seed: str) -> str:
    return re.sub(r"\s+", " ", seed.strip().lower())


def station_id(seed: str) -> str:
    return normalize_station_seed(seed)


def display_station_name(seed: str) -> str:
    cleaned = re.sub(r"\s+", " ", seed.strip())
    return f"{cleaned} radio"


def track_key(track: Dict[str, Any]) -> str:
    uri = str(track.get("uri", "")).strip()
    if uri:
        return f"uri:{uri}"
    title = re.sub(r"\s+", " ", str(track.get("title", "")).strip().lower())
    return f"title:{title}"


class DjGooStations:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"active": {}, "stations": {}}
        with self.path.open(encoding="utf-8") as fp:
            data = json.load(fp)
        if not isinstance(data, dict):
            return {"active": {}, "stations": {}}
        data.setdefault("active", {})
        data.setdefault("stations", {})
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=True)
            fp.write("\n")

    def get_or_create(self, seed: str) -> Dict[str, Any]:
        data = self._read()
        sid = station_id(seed)
        now = time.time()
        station = data["stations"].get(sid)
        if station is None:
            station = {
                "id": sid,
                "name": display_station_name(seed),
                "seed": re.sub(r"\s+", " ", seed.strip()),
                "created_at": now,
                "updated_at": now,
                "played": [],
                "recent": [],
                "liked": [],
                "banned": [],
                "more_like": [],
                "less_like": [],
                "skipped": [],
                "last_track": None,
            }
            data["stations"][sid] = station
        station["updated_at"] = now
        self._write(data)
        return station

    def get_station(self, seed: str) -> Optional[Dict[str, Any]]:
        return self._read()["stations"].get(station_id(seed))

    def set_active(self, guild_id: int, seed: str) -> Dict[str, Any]:
        data = self._read()
        station = self.get_or_create(seed)
        data = self._read()
        data["active"][str(guild_id)] = station["id"]
        self._write(data)
        return station

    def get_active(self, guild_id: int) -> Optional[Dict[str, Any]]:
        data = self._read()
        sid = data["active"].get(str(guild_id))
        if not sid:
            return None
        return data["stations"].get(sid)

    def add_feedback(self, seed: str, bucket: str, track: Dict[str, Any]) -> None:
        data = self._read()
        station = self.get_or_create(seed)
        data = self._read()
        station = data["stations"][station["id"]]
        items = station.setdefault(bucket, [])
        key = track_key(track)
        if all(track_key(existing) != key for existing in items):
            items.append({"title": str(track.get("title", "")), "uri": str(track.get("uri", ""))})
        station["updated_at"] = time.time()
        self._write(data)

    def mark_played(self, seed: str, track: Dict[str, Any]) -> None:
        data = self._read()
        station = self.get_or_create(seed)
        data = self._read()
        station = data["stations"][station["id"]]
        saved = {"title": str(track.get("title", "")), "uri": str(track.get("uri", ""))}
        key = track_key(saved)
        if all(track_key(existing) != key for existing in station["played"]):
            station["played"].append(saved)
        station["recent"] = [item for item in station["recent"] if track_key(item) != key]
        station["recent"].append(saved)
        station["recent"] = station["recent"][-RECENT_LIMIT:]
        station["last_track"] = saved
        station["updated_at"] = time.time()
        self._write(data)

    def pick_candidate(
        self,
        seed: str,
        candidates: List[Dict[str, Any]],
        *,
        rng_seed: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        station = self.get_or_create(seed)
        banned = {track_key(item) for item in station["banned"]}
        recent = {track_key(item) for item in station["recent"]}
        eligible = [item for item in candidates if track_key(item) not in banned | recent]
        if not eligible:
            eligible = [item for item in candidates if track_key(item) not in banned]
        if not eligible:
            return None
        rng = random.Random(rng_seed)
        rng.shuffle(eligible)
        return eligible[0]
```

- [x] **Step 4: Run station tests**

Run:

```powershell
$env:PYTHONPATH='C:\Users\VERA\Documents\DiscordBot'
.\.voice-venv\Scripts\python.exe -m unittest tests.test_djgoo_stations -v
```

Expected: `Ran 4 tests ... OK`.

- [x] **Step 5: Commit**

```powershell
git add voice/djgoo_stations.py tests/test_djgoo_stations.py
git commit -m "feat: add DjGoo station store"
```

---

### Task 2: Voice Parser Radio Commands

**Files:**
- Modify: `voice/command_parser.py`
- Modify: `tests/test_voice_command_parser.py`

- [x] **Step 1: Write failing parser tests**

Add to `VoiceCommandParserTests` in `tests/test_voice_command_parser.py`:

```python
    def test_parses_radio_station_commands(self):
        radio = parse_command("DjGoo radio Sandstorm")
        self.assertEqual(radio.intent, "start_radio")
        self.assertEqual(radio.query, "Sandstorm")

        examples = {
            "DjGoo like this": "station_like_current",
            "DjGoo more like this": "station_more_like_current",
            "DjGoo less like this": "station_less_like_current",
            "DjGoo don't play this again": "station_ban_current",
            "DjGoo do not play this again": "station_ban_current",
            "DjGoo station status": "station_status",
        }
        for transcript, intent in examples.items():
            with self.subTest(transcript=transcript):
                self.assertEqual(parse_command(transcript).intent, intent)
```

- [x] **Step 2: Run parser tests to verify failure**

Run:

```powershell
$env:PYTHONPATH='C:\Users\VERA\Documents\DiscordBot'
.\.voice-venv\Scripts\python.exe -m unittest tests.test_voice_command_parser -v
```

Expected: fails because `radio` and station curation commands parse as `unknown` or existing unrelated intents.

- [x] **Step 3: Implement parser intents**

Modify `voice/command_parser.py` inside `parse_command` after `lowered = command.lower()` and before playlist handling:

```python
    if lowered.startswith("radio "):
        query = _normalize(command[len("radio ") :])
        return ParsedCommand(intent="start_radio", query=query, confidence=0.95, raw=raw)
```

Add these entries near the start of `phrase_intents`:

```python
        (("don't play this again", "do not play this again", "ban this", "never play this"), "station_ban_current"),
        (("more like this",), "station_more_like_current"),
        (("less like this",), "station_less_like_current"),
        (("like this", "i like this"), "station_like_current"),
        (("station status", "radio status"), "station_status"),
```

Place `more like this` and `less like this` before `like this` so they do not get swallowed by the shorter phrase.

- [x] **Step 4: Run parser tests**

Run:

```powershell
$env:PYTHONPATH='C:\Users\VERA\Documents\DiscordBot'
.\.voice-venv\Scripts\python.exe -m unittest tests.test_voice_command_parser -v
```

Expected: parser tests pass.

- [x] **Step 5: Commit**

```powershell
git add voice/command_parser.py tests/test_voice_command_parser.py
git commit -m "feat: parse DjGoo radio commands"
```

---

### Task 3: Station Overlay Payload

**Files:**
- Modify: `local_cogs/djgoowelcome/helpers.py`
- Modify: `tests/test_djgoowelcome_helpers.py`

- [ ] **Step 1: Write failing overlay test**

Add to `DjGooWelcomeHelperTests`:

```python
    def test_build_station_track_payload_is_visual_only_and_glanceable(self):
        helpers = load_helpers()

        payload = helpers.build_station_track_payload(
            station_name="Sandstorm radio",
            track={"title": "Kernkraft 400", "uri": "https://example.test/kernkraft"},
            reason="Fresh similar pick",
        )

        self.assertEqual(payload["username"], "DjGoo")
        self.assertNotIn("content", payload)
        embed = payload["embeds"][0]
        self.assertIn("Kernkraft 400", embed["title"])
        self.assertIn("Sandstorm radio", embed["description"])
        self.assertIn("Fresh similar pick", embed["description"])
        self.assertIn("like this", embed["footer"]["text"])
```

- [ ] **Step 2: Run helper tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_djgoowelcome_helpers -v
```

Expected: fails with `AttributeError: module 'djgoowelcome_helpers' has no attribute 'build_station_track_payload'`.

- [ ] **Step 3: Implement station overlay builder**

Add to `local_cogs/djgoowelcome/helpers.py`:

```python
def build_station_track_payload(
    *,
    station_name: str,
    track: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    title = str(track.get("title", "")).strip() or "Radio pick"
    uri = str(track.get("uri", "")).strip()
    description_lines = [
        f"Station: **{station_name}**",
        f"Why: {reason}",
    ]
    if uri:
        description_lines.append(f"[Open track]({uri})")
    return {
        "username": "DjGoo",
        "embeds": [
            {
                "title": title[:256],
                "description": "\n".join(description_lines)[:4096],
                "color": 0x9B51E0,
                "footer": {
                    "text": "DjGoo like this | more like this | less like this | don't play this again"
                },
            }
        ],
    }
```

- [ ] **Step 4: Run helper tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_djgoowelcome_helpers -v
```

Expected: helper tests pass.

- [ ] **Step 5: Commit**

```powershell
git add local_cogs/djgoowelcome/helpers.py tests/test_djgoowelcome_helpers.py
git commit -m "feat: add station track overlay"
```

---

### Task 4: Audio Bridge Radio Execution

**Files:**
- Modify: `local_cogs/djgoowelcome/audio_bridge.py`
- Modify: `local_cogs/djgoowelcome/djgoowelcome.py` only if imports need updating.
- Test manually through queue because Red/Lavalink runtime objects are hard to unit test safely.

- [ ] **Step 1: Add imports and station store**

Modify imports in `local_cogs/djgoowelcome/audio_bridge.py`:

```python
from voice.djgoo_stations import DjGooStations, track_key
from .helpers import build_station_track_payload
```

In `DjGooAudioBridge.__init__`, add:

```python
        self.stations = DjGooStations(project_root / "data" / "djgoo-stations.json")
```

- [ ] **Step 2: Add radio intent branches**

Inside `handle`, before the `play` branch, add:

```python
            if intent == "start_radio":
                return await self._start_radio(audio, ctx, str(item.get("query", "")))
            if intent == "station_like_current":
                return await self._station_feedback(ctx, "liked", "Liked this for the active station.")
            if intent == "station_more_like_current":
                return await self._station_feedback(ctx, "more_like", "Steering this station closer to this song.")
            if intent == "station_less_like_current":
                return await self._station_feedback(ctx, "less_like", "Steering this station away from this song.")
            if intent == "station_ban_current":
                result = await self._station_feedback(ctx, "banned", "This song will not play again on this station.")
                await self._invoke(audio.command_skip, ctx)
                return result
            if intent == "station_status":
                return await self._station_status(ctx)
```

- [ ] **Step 3: Add radio helper methods**

Add methods to `DjGooAudioBridge`:

```python
    async def _start_radio(self, audio, ctx, seed: str) -> str:
        seed = seed.strip()
        if not seed:
            await self._notice("Tell me what to seed the station with, like `DjGoo radio Sandstorm`.")
            return "Missing radio seed"
        station = self.stations.set_active(ctx.guild.id, seed)
        await self._invoke(audio.command_play, ctx, query=seed)
        await self._notice(f"Started `{station['name']}`. I will keep this station's taste separate.")
        return f"Started {station['name']}"

    async def _station_feedback(self, ctx, bucket: str, message: str) -> str:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            await self._notice("No active radio station yet. Start one with `DjGoo radio <song>`.")
            return "No active station"
        track = self._selected_track(ctx.guild.id, last=False)
        if track is None:
            await self._notice("I could not read the current track.")
            return "No current track"
        self.stations.add_feedback(station["seed"], bucket, self._track_data(track))
        await self._notice(message)
        return message

    async def _station_status(self, ctx) -> str:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            await self._notice("No active radio station yet.")
            return "No active station"
        await self._notice(
            f"`{station['name']}`\n"
            f"Played: `{len(station['played'])}` | "
            f"Liked: `{len(station['liked'])}` | "
            f"Banned: `{len(station['banned'])}`"
        )
        return "Station status"
```

- [ ] **Step 4: Add lightweight station marking to existing play/skip flow**

In the existing `skip` branch, before invoking skip, add:

```python
                await self._mark_station_skip(ctx)
```

Add helper:

```python
    async def _mark_station_skip(self, ctx) -> None:
        station = self.stations.get_active(ctx.guild.id)
        if station is None:
            return
        track = self._selected_track(ctx.guild.id, last=False)
        if track is not None:
            self.stations.add_feedback(station["seed"], "skipped", self._track_data(track))
```

- [ ] **Step 5: Runtime test radio queue item**

Restart DjGoo:

```powershell
.\stop-djgoo.ps1
Start-Sleep -Seconds 3
.\Start-DjGoo.command.ps1
Start-Sleep -Seconds 12
.\Start-DjGoo-Voice.command.ps1
```

Queue a synthetic radio command:

```powershell
$env:PYTHONPATH='C:\Users\VERA\Documents\DiscordBot'
@'
from pathlib import Path
from voice.command_queue import append_queue_item
append_queue_item(Path(r'C:\Users\VERA\Documents\DiscordBot\data\voice-command-queue.jsonl'), {
    'type': 'command',
    'source': 'voice-test',
    'created_at': 0,
    'intent': 'start_radio',
    'query': 'Sandstorm',
    'playlist': '',
    'value': None,
    'confidence': 1.0,
    'raw': 'DjGoo radio Sandstorm'
})
'@ | .\.voice-venv\Scripts\python.exe -
Start-Sleep -Seconds 5
if (Test-Path 'C:\Users\VERA\Documents\DiscordBot\data\voice-command-queue.jsonl') {
  Get-Content -Raw -LiteralPath 'C:\Users\VERA\Documents\DiscordBot\data\voice-command-queue.jsonl'
} else {
  'QUEUE_DRAINED'
}
```

Expected: `QUEUE_DRAINED`. If no one is in voice, Discord overlay should say to join voice; if someone is in voice, Red should attempt to play `Sandstorm` and `data/djgoo-stations.json` should contain `Sandstorm radio`.

- [ ] **Step 6: Commit**

```powershell
git add local_cogs/djgoowelcome/audio_bridge.py local_cogs/djgoowelcome/djgoowelcome.py
git commit -m "feat: wire radio station commands"
```

---

### Task 5: Radio Queue Top-Up and Overlay

**Files:**
- Modify: `local_cogs/djgoowelcome/djgoowelcome.py`
- Modify: `local_cogs/djgoowelcome/audio_bridge.py`

- [ ] **Step 1: Add event listener for track starts**

In `local_cogs/djgoowelcome/djgoowelcome.py`, add:

```python
    @commands.Cog.listener()
    async def on_red_audio_track_start(self, player, track, requester):
        await self._audio_bridge.handle_station_track_start(player, track)
```

- [ ] **Step 2: Add bridge method to mark played and post station card**

Add to `DjGooAudioBridge`:

```python
    async def handle_station_track_start(self, player, track) -> None:
        station = self.stations.get_active(player.guild.id)
        if station is None:
            return
        data = self._track_data(track)
        self.stations.mark_played(station["seed"], data)
        await self._send_payload(
            build_station_track_payload(
                station_name=station["name"],
                track=data,
                reason=self._station_reason(station),
            )
        )

    def _station_reason(self, station: Dict[str, Any]) -> str:
        if station.get("liked"):
            return "Because you liked tracks on this station"
        if station.get("more_like"):
            return "Steered by more-like-this"
        return "Fresh similar pick"
```

- [ ] **Step 3: Add simple top-up after track start**

At the end of `handle_station_track_start`, after the overlay call, add:

```python
        await self._top_up_station_queue(player.guild.id)
```

Add helper:

```python
    async def _top_up_station_queue(self, guild_id: int) -> None:
        station = self.stations.get_active(guild_id)
        if station is None:
            return
        audio = self.bot.get_cog("Audio")
        ctx = self._context()
        if audio is None or ctx is None:
            return
        try:
            player = lavalink.get_player(guild_id)
        except (NodeNotFound, PlayerNotFound):
            return
        if len(player.queue) >= 2:
            return
        seeds = [station["seed"]]
        if station.get("liked"):
            seeds.append(station["liked"][-1]["title"])
        if station.get("more_like"):
            seeds.append(station["more_like"][-1]["title"])
        query = f"{random.choice(seeds)} similar music"
        await self._invoke(audio.command_play, ctx, query=query)
```

This is the first-pass free candidate generation. It keeps the queue alive and uses station memory to vary search phrases while staying inside Red Audio and Lavalink.

- [ ] **Step 4: Runtime test no log errors**

Run a synthetic `start_radio`, then check logs:

```powershell
Select-String -Path 'C:\Users\VERA\Documents\DiscordBot\data\discordbot\core\logs\latest.log' -Pattern 'Failed to load|Traceback|ERROR|DjGoo voice command queue loop failed|That command hit an error'
```

Expected: no matching current errors.

- [ ] **Step 5: Commit**

```powershell
git add local_cogs/djgoowelcome/audio_bridge.py local_cogs/djgoowelcome/djgoowelcome.py
git commit -m "feat: add station track overlay and queue top-up"
```

---

### Task 6: README and Full Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document radio commands**

Add to `README.md`:

```markdown
## Radio Stations

Playlists and stations are separate.

Start or resume a station:

```text
DjGoo radio Sandstorm
```

This creates or resumes `Sandstorm radio`.

Curate the active station:

```text
DjGoo like this
DjGoo more like this
DjGoo less like this
DjGoo don't play this again
DjGoo station status
```

Station memory is stored in:

```text
data\djgoo-stations.json
```

Radio overlays are visual-only Discord embeds.
```

- [ ] **Step 2: Run all tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$env:PYTHONPATH='C:\Users\VERA\Documents\DiscordBot'
.\.voice-venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Expected:

```text
OK
OK
No broken requirements found.
```

- [ ] **Step 3: Runtime status check**

Run:

```powershell
Get-CimInstance Win32_Process | Where-Object {
  ($_.Name -in @('redbot.exe','python.exe','java.exe')) -and
  ($_.CommandLine -like '*DiscordBot*' -or $_.CommandLine -like '*voice.djgoo_voice_listener*' -or $_.CommandLine -like '*Lavalink.jar*')
} | Select-Object Name,ProcessId,CommandLine | Format-List
```

Expected: Redbot, Lavalink Java, and the voice listener are present.

- [ ] **Step 4: Commit docs**

```powershell
git add README.md
git commit -m "docs: document DjGoo radio stations"
```

---

## Self-Review Notes

- Spec coverage: station identity, separate storage, curation commands, visual-only overlays, anti-repeat memory, no paid APIs, and runtime verification are covered.
- First-pass limitation: candidate generation is free and simple. It uses Red Audio search phrases plus station memory rather than paid recommendation APIs or ML embeddings.
- Type consistency: station store uses plain dictionaries with `title` and `uri`, matching current playlist storage and audio bridge track conversion.
