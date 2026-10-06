from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

from control_panel.state import build_remote_state_snapshot
from local_cogs.djgoowelcome.djgoowelcome import DjGooWelcome
from voice.command_acceptance import AuthenticatedCommandProcessor, AuthorizationResult, CommandRejected
from voice.pairing_store import PairingStore


WEB_CAPS = ("state.read", "queue.read", "playback.request", "playback.vote_skip")


@pytest.mark.asyncio
async def test_remote_state_is_available_when_member_is_not_in_voice() -> None:
    class Member:
        id = 12
        voice = None
        guild_permissions = type("Permissions", (), {"manage_guild": False})()

    class Guild:
        owner_id = 99
        voice_client = None

        def get_member(self, user_id):
            return Member() if user_id == 12 else None

    class Bot:
        def get_guild(self, guild_id):
            return Guild() if guild_id == 34 else None

    cog = object.__new__(DjGooWelcome)
    cog.bot = Bot()
    identity = type("Identity", (), {"guild_id": 34, "user_id": 12})()

    result = await cog._authorize_remote(identity, "state.read")

    assert result.allowed is True
    assert result.voice_channel_id == 0


def store(tmp_path: Path) -> PairingStore:
    return PairingStore(tmp_path / "pairing.db", tmp_path / "secret.bin")


def web_device(pairing: PairingStore):
    code = pairing.create_pairing_code(12, 34, device_type="web", capabilities=WEB_CAPS)
    return pairing.redeem_pairing_code(code, "Browser")


@pytest.mark.asyncio
async def test_web_pairing_is_typed_single_use_and_revocable(tmp_path: Path) -> None:
    pairing = store(tmp_path)
    code = pairing.create_pairing_code(12, 34, device_type="web", capabilities=WEB_CAPS)
    identity, token = pairing.redeem_pairing_code(code, "Browser")
    assert identity.device_type == "web"
    assert set(identity.capabilities) == set(WEB_CAPS)
    assert pairing.redeem_pairing_code(code, "Replay") is None
    assert pairing.revoke_device(identity.device_id, 12, 34)
    assert pairing.authenticate(token) is None


@pytest.mark.asyncio
async def test_web_capabilities_and_replay_are_enforced_host_side(tmp_path: Path) -> None:
    pairing = store(tmp_path)
    identity, token = web_device(pairing)
    async def authorize(_identity, _intent): return AuthorizationResult(True, voice_channel_id=99, actor_role="host")
    async def state(_identity): return {"playback": {}, "queue": []}
    processor = AuthenticatedCommandProcessor(pairing, tmp_path / "queue.jsonl", authorize, state)
    command_id = str(uuid.uuid4())
    payload = {"command_id": command_id, "created_at": time.time(), "intent": "play", "query": "Sandstorm", "guild_id": "34", "actor_role": "host", "is_admin": True}
    assert (await processor.accept(token, payload))["duplicate"] is False
    assert (await processor.accept(token, payload))["duplicate"] is True
    queued = json.loads((tmp_path / "queue.jsonl").read_text().strip())
    assert queued["user_id"] == 12 and queued["guild_id"] == 34
    assert queued["actor_role"] == "host"
    assert queued["source"] == "web_remote" and queued["control_surface"] == "web"
    assert "is_admin" not in queued
    with pytest.raises(CommandRejected, match="not enabled"):
        await processor.accept(token, {**payload, "command_id": str(uuid.uuid4()), "intent": "stop"})
    with pytest.raises(CommandRejected, match="not paired"):
        await processor.accept(token, {**payload, "command_id": str(uuid.uuid4()), "guild_id": "999"})
    assert (await processor.remote_state(token))["queue"] == []


@pytest.mark.asyncio
async def test_web_music_search_is_authenticated_and_returns_choices(tmp_path: Path) -> None:
    pairing = store(tmp_path)
    identity, token = web_device(pairing)
    searches = []

    async def authorize(_identity, intent):
        assert intent == "state.read"
        return AuthorizationResult(True, actor_role="host")

    async def search(search_identity, query, limit):
        searches.append((search_identity.device_id, query, limit))
        return [{"title": "Ich Will", "artist": "Rammstein", "uri": "https://example.invalid/track"}]

    processor = AuthenticatedCommandProcessor(
        pairing,
        tmp_path / "queue.jsonl",
        authorize,
        search_provider=search,
    )

    result = await processor.search(token, "  ich will  ", limit=8)

    assert result["query"] == "ich will"
    assert result["results"][0]["title"] == "Ich Will"
    assert searches == [(identity.device_id, "ich will", 8)]
    with pytest.raises(CommandRejected, match="authentication failed"):
        await processor.search("invalid-token", "ich will")


def test_remote_state_matches_control_surface_but_excludes_private_data(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir(); (tmp_path / "logs").mkdir()
    (tmp_path / "data" / "djgoo-now-playing.json").write_text(json.dumps({"current": {"title": "Song", "artist": "Artist"}, "queue": [{"id": "1", "title": "Next", "uri": "https://secret.invalid"}]}))
    (tmp_path / "logs" / "startup.log").write_text("bot_token=secret C:/private/path")
    state = build_remote_state_snapshot(tmp_path)
    encoded = json.dumps(state)
    assert state["playback"]["title"] == "Song"
    assert state["logs"] == {} and "health" in state
    assert "playlists" in state and "stations" in state and "gaming" in state
    assert "secret.invalid" not in encoded and "private/path" not in encoded and "bot_token" not in encoded
    assert state["capabilities"]["system_management"] is False


def test_remote_state_includes_safe_recent_history(tmp_path: Path) -> None:
    from voice.mini_player_protocol import MiniPlayerHistory

    history = MiniPlayerHistory(tmp_path / "data" / "djgoo-mini-history.json")
    history.add(
        {"id": "recent-1", "title": "Recent Song", "artist": "Artist", "uri": "C:/private/song.webm"},
        mode="PLAYBACK",
    )

    state = build_remote_state_snapshot(tmp_path)

    assert state["history"][0]["title"] == "Recent Song"
    assert state["history"][0]["id"] == "recent-1"
    assert "uri" not in state["history"][0]


def test_remote_frontend_erases_fragment_and_reuses_shared_app() -> None:
    root = Path(__file__).resolve().parents[1] / "control_panel_ui"
    main = (root / "src" / "main.tsx").read_text(encoding="utf-8")
    remote = (root / "src" / "RemoteApp.tsx").read_text(encoding="utf-8")
    app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
    transport = (root / "src" / "remoteTransport.ts").read_text(encoding="utf-8")
    api = (root / "src" / "api.ts").read_text(encoding="utf-8")
    worker = (root / "public" / "service-worker.js").read_text(encoding="utf-8")
    assert "history.replaceState" in remote
    assert 'window.location.hostname === "vamparion.github.io"' in main
    assert "getRegistrations" in main and "registration.unregister()" in main
    assert "djgoo-pending-web-invite" in main
    assert '!remoteMode && "serviceWorker"' in main
    assert "<App />" in remote
    assert "inviteMatchesCredential(invite, stored)" in remote
    assert "useState(true)" in remote
    assert "if (!invite)" in remote and "/djgoo web" in remote
    assert "djgoo-web-remembered" in remote
    assert "document.hidden" in app and "visibilitychange" in app
    assert "/api/system" not in remote and "/api/system" not in transport
    assert "actor_role" not in transport and "is_admin" not in transport
    assert "url.origin !== self.location.origin" in worker
    assert "self.skipWaiting()" in worker and "self.clients.claim()" in worker
    assert "discordJson(created" in transport and "discordJson(response" in transport
    assert "pollDiscordMessage" in transport and '"discordapp.com"' in transport
    assert "new WebSocket" in transport and "credentialWithInviteRoutes" in transport
    assert 'transport === "relay"' in transport and "RelaySocketSession" in transport
    assert "stateRefreshIntervalMs()" in app
    assert "subscribeState" in app and "setState(next)" in app
    assert "reconnectRemote()" in app and "void poll()" in app
    assert "isRemoteDirectConnected(remoteCredential) ? 60000 : 8000" in api
    assert "HostRejection" in transport and "command_id: crypto.randomUUID()" in transport
    assert "const command =" in transport and "...command, device_token" in transport
    assert "device_token" not in worker and "#pair=" not in worker


def test_find_returns_choices_and_queue_uses_a_modal() -> None:
    root = Path(__file__).resolve().parents[1] / "control_panel_ui" / "src"
    app = (root / "App.tsx").read_text(encoding="utf-8")
    search = (root / "components" / "SearchPanel.tsx").read_text(encoding="utf-8")
    queue_modal = (root / "components" / "QueueModal.tsx").read_text(encoding="utf-8")
    styles = (root / "styles.css").read_text(encoding="utf-8")

    assert 'if (action === "queue")' in app and "setQueueOpen(true)" in app
    assert "<QueueModal" in app and "<QueuePanel" not in app
    assert "searchMusic(q)" in search
    assert 'event.key === "Enter"' in search and "void search()" in search
    assert 'send("play", { query: track.uri })' in search
    assert 'send("play_next", { query: track.uri })' in search
    assert "position: fixed" in styles and "queue-modal" in queue_modal


def test_local_and_paired_web_use_shared_history_and_theme() -> None:
    root = Path(__file__).resolve().parents[1] / "control_panel_ui" / "src"
    app = (root / "App.tsx").read_text(encoding="utf-8")
    remote = (root / "RemoteApp.tsx").read_text(encoding="utf-8")
    history = (root / "components" / "HistoryPanel.tsx").read_text(encoding="utf-8")
    playlists = (root / "components" / "PlaylistPanel.tsx").read_text(encoding="utf-8")

    assert "return <App />" in remote
    assert '"History"' in app and "<HistoryPanel" in app
    assert 'playlistAction("history-add"' in history
    assert 'playlistAction("history-delete"' in history
    assert 'getData("text/djgoo-history")' in history
    assert 'playlistAction("create"' in playlists
    assert "new-playlist-drop" in playlists
    assert 'getData("text/djgoo-history")' in playlists
    assert ': "host"' in app and "isRemoteSession()" in app


def test_live_and_playlist_surfaces_keep_controls_contextual() -> None:
    root = Path(__file__).resolve().parents[1] / "control_panel_ui" / "src"
    app = (root / "App.tsx").read_text(encoding="utf-8")
    live = (root / "components" / "LivePanel.tsx").read_text(encoding="utf-8")
    playlists = (root / "components" / "PlaylistPanel.tsx").read_text(encoding="utf-8")

    assert 'openFind={() => setActiveView("Find")}' in app
    assert "!hasTrack ?" in live and "radioActive &&" in live
    assert 'send("reset")' not in live
    assert "playlist-track-row" in playlists
    assert "bulk.trim() &&" in playlists
    assert "Playlist details" in playlists and "Add from history" in playlists


def test_game_first_ui_supports_sticky_drops_touch_destinations_and_stop() -> None:
    root = Path(__file__).resolve().parents[1] / "control_panel_ui" / "src"
    search = (root / "components" / "SearchPanel.tsx").read_text(encoding="utf-8")
    history = (root / "components" / "HistoryPanel.tsx").read_text(encoding="utf-8")
    player = (root / "components" / "LivePanel.tsx").read_text(encoding="utf-8")
    footer = (root / "components" / "PersistentFooter.tsx").read_text(encoding="utf-8")
    radio = (root / "components" / "StationPanel.tsx").read_text(encoding="utf-8")
    styles = (root / "styles.css").read_text(encoding="utf-8")

    assert 'draggable key=' in search and 'application/djgoo-track' in search
    assert "Add to..." in search and 'value="queue"' in search
    assert "sticky-drop-targets" in history and "position: sticky" in styles
    assert 'send("stop")' in player and 'send("stop")' in footer
    assert "playback.artwork_url" in player and "playback.artwork_url" in footer
    assert "Advanced station settings" in radio and "Artist repeat spacing" in radio


def test_hosted_relay_accepts_web_state_and_web_invites_can_offer_relay() -> None:
    root = Path(__file__).resolve().parents[1]
    relay_host = (root / "voice" / "relay_host.py").read_text(encoding="utf-8")
    relay_cog = (root / "local_cogs" / "djgoowelcome" / "relay_cog.py").read_text(encoding="utf-8")

    assert 'action == "web/state"' in relay_host
    assert "async def _web_relay_endpoint" in relay_cog
    assert 'transport="relay"' in relay_cog
    assert "device_type=\"web\"" in relay_cog


def test_guest_stop_is_not_admin_only_and_web_retries_are_deduplicated() -> None:
    root = Path(__file__).resolve().parents[1]
    cog = (root / "local_cogs" / "djgoowelcome" / "djgoowelcome.py").read_text(encoding="utf-8")
    requests = (root / "local_cogs" / "djgoowelcome" / "request_semantics_bridge.py").read_text(encoding="utf-8")
    destructive = cog.split("DESTRUCTIVE_REMOTE_INTENTS = {", 1)[1].split("}", 1)[0]

    assert '"stop"' not in destructive
    assert 'source in {"mini_player", "web_remote"}' in requests
    assert '"request.control_surface.duplicate_rejected"' in requests


def test_shipped_web_ui_has_no_personal_test_shortcuts() -> None:
    source_root = Path(__file__).resolve().parents[1] / "control_panel_ui" / "src"
    shipped = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*")
        if path.suffix in {".ts", ".tsx"} and not path.name.endswith(".test.ts")
    ).casefold()
    for personal_example in ("sandstorm", "white girl music", "rocket league edm", "radio 80s"):
        assert personal_example not in shipped
