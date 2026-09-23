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
    assert "is_admin" not in queued
    with pytest.raises(CommandRejected, match="not enabled"):
        await processor.accept(token, {**payload, "command_id": str(uuid.uuid4()), "intent": "stop"})
    with pytest.raises(CommandRejected, match="not paired"):
        await processor.accept(token, {**payload, "command_id": str(uuid.uuid4()), "guild_id": "999"})
    assert (await processor.remote_state(token))["queue"] == []


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


def test_remote_frontend_erases_fragment_and_reuses_shared_app() -> None:
    root = Path(__file__).resolve().parents[1] / "control_panel_ui"
    main = (root / "src" / "main.tsx").read_text(encoding="utf-8")
    remote = (root / "src" / "RemoteApp.tsx").read_text(encoding="utf-8")
    app = (root / "src" / "App.tsx").read_text(encoding="utf-8")
    transport = (root / "src" / "remoteTransport.ts").read_text(encoding="utf-8")
    api = (root / "src" / "api.ts").read_text(encoding="utf-8")
    worker = (root / "public" / "service-worker.js").read_text(encoding="utf-8")
    assert "history.replaceState" in main
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
    assert 'endpoint.transport === "relay"' in transport
    assert "stateRefreshIntervalMs()" in app
    assert 'remoteTransportKind(remoteCredential) === "relay" ? 3000 : 12000' in api
    assert "device_token" not in worker and "#pair=" not in worker


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
