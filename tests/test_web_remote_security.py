from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

from control_panel.state import build_remote_state_snapshot
from voice.command_acceptance import AuthenticatedCommandProcessor, AuthorizationResult, CommandRejected
from voice.pairing_store import PairingStore


WEB_CAPS = ("state.read", "queue.read", "playback.request", "playback.vote_skip")


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
    worker = (root / "public" / "service-worker.js").read_text(encoding="utf-8")
    assert "history.replaceState" in main
    assert "<App />" in remote
    assert "invite ? null : storedCredential()" in remote
    assert "djgoo-web-remembered" in remote
    assert "document.hidden" in app and "visibilitychange" in app
    assert "/api/system" not in remote and "/api/system" not in transport
    assert "actor_role" not in transport and "is_admin" not in transport
    assert "url.origin !== self.location.origin" in worker
    assert "self.skipWaiting()" in worker and "self.clients.claim()" in worker
    assert "discordJson(created" in transport and "discordJson(response" in transport
    assert "device_token" not in worker and "#pair=" not in worker
