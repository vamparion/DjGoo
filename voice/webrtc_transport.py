from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from voice.command_acceptance import AuthenticatedCommandProcessor, CommandRejected
from voice.operational_log import log_event
from tools.runtime_layers import activate_host_webrtc_layer


DEFAULT_ICE_SERVERS = ("stun:stun.l.google.com:19302",)
NEGOTIATION_TTL_SECONDS = 90.0
SESSION_TTL_SECONDS = 60 * 60.0
MAX_SESSIONS = 64


@dataclass
class RemoteStateRevision:
    revision: int = 0
    queue_revision: int = 0
    _last_fingerprint: str = ""
    _last_queue_fingerprint: str = ""

    def snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        playback = state.get("playback") if isinstance(state.get("playback"), dict) else {}
        stable_playback = {
            key: value
            for key, value in playback.items()
            if key not in {"position_ms", "position_seconds", "remaining", "measured_at", "generated_at"}
        }
        queue = state.get("queue") if isinstance(state.get("queue"), list) else []
        state_fingerprint = json.dumps(
            {
                "playback": stable_playback,
                "health_summary": state.get("health_summary") or {},
                "active_station": state.get("active_station") or {},
                "gaming": state.get("gaming") or {},
                "playlists": state.get("playlists") or [],
                "stations": state.get("stations") or [],
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        queue_fingerprint = json.dumps(
            queue,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        if state_fingerprint != self._last_fingerprint:
            self.revision += 1
            self._last_fingerprint = state_fingerprint
        if queue_fingerprint != self._last_queue_fingerprint:
            self.queue_revision += 1
            self._last_queue_fingerprint = queue_fingerprint
            self.revision += 1
        payload = dict(state)
        payload["revision"] = self.revision
        payload["queue_revision"] = self.queue_revision
        payload["generated_at"] = float(payload.get("generated_at") or time.time())
        return payload


@dataclass
class WebRtcSession:
    session_id: str
    device_id: str
    created_at: float
    updated_at: float
    token: str = field(repr=False)
    peer: Any = None
    channel: Any = None
    closed: bool = False
    revision: RemoteStateRevision = field(default_factory=RemoteStateRevision)
    last_sent_revision: int = 0


class WebRtcUnavailable(RuntimeError):
    pass


class WebRtcSignalManager:
    """Host-side WebRTC control channel manager.

    Signaling is intentionally transport-agnostic: callers deliver authenticated,
    encrypted signaling messages over Discord/relay/direct envelopes, and this
    class handles only peer lifecycle and DataChannel requests. DTLS protects the
    channel in transit; DjGoo authorization remains bound to the paired device token
    authenticated during signaling and is checked again for every request.
    """

    def __init__(
        self,
        processor: AuthenticatedCommandProcessor,
        *,
        ice_servers: tuple[str, ...] = DEFAULT_ICE_SERVERS,
        negotiation_ttl_seconds: float = NEGOTIATION_TTL_SECONDS,
        session_ttl_seconds: float = SESSION_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self.processor = processor
        self.ice_servers = tuple(ice_servers or DEFAULT_ICE_SERVERS)
        self.negotiation_ttl_seconds = float(negotiation_ttl_seconds)
        self.session_ttl_seconds = float(session_ttl_seconds)
        self.max_sessions = int(max_sessions)
        self._sessions: dict[str, WebRtcSession] = {}
        self._lock = asyncio.Lock()

    async def signal(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = str(payload.get("device_token") or "")
        status = await self.processor.status(token)
        device_id = str(status["device_id"])
        kind = str(payload.get("type") or "")
        await self._prune()
        if kind == "offer":
            return await self._accept_offer(device_id, token, payload)
        if kind == "candidate":
            raise CommandRejected(400, "DjGoo uses complete non-trickle ICE offers")
        if kind == "close":
            await self.close(str(payload.get("session_id") or ""), device_id=device_id)
            return {"accepted": True}
        if kind == "status":
            return {
                "available": self.available(),
                "sessions": [
                    session.session_id
                    for session in self._sessions.values()
                    if session.device_id == device_id and not session.closed
                ],
                "ice_servers": self.ice_servers,
            }
        raise CommandRejected(400, "Unknown WebRTC signaling action")

    def available(self) -> bool:
        try:
            self._aiortc()
            return True
        except WebRtcUnavailable:
            return False

    async def close(self, session_id: str, *, device_id: str | None = None) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            if device_id is not None and session.device_id != device_id:
                raise CommandRejected(403, "WebRTC session belongs to another device")
            self._sessions.pop(session_id, None)
        await self._close_session(session)
        log_event("web.remote.transport.webrtc.closed", session_id=session_id)

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        await asyncio.gather(*(self._close_session(session) for session in sessions))

    async def publish_state(self) -> None:
        stale: list[str] = []
        for session in list(self._sessions.values()):
            channel = session.channel
            if session.closed or channel is None:
                continue
            if str(getattr(channel, "readyState", "")) != "open":
                continue
            try:
                state = await self.processor.remote_state(session.token)
                snapshot = session.revision.snapshot(state)
                if snapshot["revision"] == session.last_sent_revision:
                    continue
                message = json.dumps(
                    {"type": "state", "state": snapshot},
                    separators=(",", ":"),
                    ensure_ascii=True,
                    default=str,
                )
                channel.send(message)
                session.last_sent_revision = int(snapshot["revision"])
                session.updated_at = time.monotonic()
            except Exception:
                stale.append(session.session_id)
        for session_id in stale:
            await self.close(session_id)

    async def _close_session(self, session: WebRtcSession) -> None:
        if session.closed:
            return
        session.closed = True
        channel = session.channel
        session.channel = None
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass
        peer = session.peer
        session.peer = None
        if peer is not None:
            try:
                result = peer.close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    async def _accept_offer(
        self,
        device_id: str,
        token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer = self._aiortc()
        offer = payload.get("offer")
        if not isinstance(offer, dict):
            raise CommandRejected(400, "WebRTC offer is required")
        sdp = str(offer.get("sdp") or "")
        offer_type = str(offer.get("type") or "offer")
        if offer_type != "offer" or not sdp:
            raise CommandRejected(400, "Invalid WebRTC offer")
        session_id = str(payload.get("session_id") or uuid.uuid4())
        peer = RTCPeerConnection(
            configuration=RTCConfiguration(
                iceServers=[RTCIceServer(urls=list(self.ice_servers))]
            )
        )
        session = WebRtcSession(
            session_id=session_id,
            device_id=device_id,
            created_at=time.monotonic(),
            updated_at=time.monotonic(),
            token=token,
            peer=peer,
        )
        try:
            self._wire_peer(session, token)
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
            answer = await peer.createAnswer()
            await peer.setLocalDescription(answer)
            await self._replace_device_sessions(device_id)
            async with self._lock:
                self._sessions[session_id] = session
            await self._enforce_session_limit()
        except BaseException:
            await self._close_session(session)
            raise
        log_event("web.remote.signaling.completed", session_id=session_id)
        return {
            "accepted": True,
            "session_id": session_id,
            "answer": {
                "type": peer.localDescription.type,
                "sdp": peer.localDescription.sdp,
            },
            "ice_servers": list(self.ice_servers),
            "expires_at": time.time() + self.negotiation_ttl_seconds,
        }

    def _wire_peer(self, session: WebRtcSession, token: str) -> None:
        peer = session.peer

        @peer.on("datachannel")
        def on_datachannel(channel: Any) -> None:
            session.channel = channel
            log_event(
                "web.remote.transport.webrtc.connected",
                session_id=session.session_id,
            )
            asyncio.create_task(self._send_session_state(session, force=True))

            @channel.on("message")
            def on_message(message: Any) -> None:
                asyncio.create_task(
                    self._handle_channel_message(session, token, message)
                )

        @peer.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            state = str(getattr(peer, "connectionState", ""))
            if state in {"failed", "closed", "disconnected"}:
                log_event(
                    "web.remote.transport.webrtc.failed",
                    session_id=session.session_id,
                    state=state,
                )
                await self.close(session.session_id)

    async def _handle_channel_message(
        self,
        session: WebRtcSession,
        token: str,
        message: Any,
    ) -> None:
        session.updated_at = time.monotonic()
        channel = session.channel
        request_id = str(uuid.uuid4())
        try:
            payload = json.loads(message if isinstance(message, str) else message.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Message must be an object")
            request_id = str(payload.get("request_id") or request_id)
            kind = str(payload.get("type") or "")
            if kind == "command":
                body = payload.get("command")
                if not isinstance(body, dict):
                    raise CommandRejected(400, "Command payload is required")
                result = await self.processor.accept(token, body)
            elif kind in {"state", "reconcile"}:
                result = await self._send_session_state(session, force=True)
            elif kind == "ping":
                result = {"pong": True, "now": time.time()}
            else:
                raise CommandRejected(400, "Unknown WebRTC message")
            response = {"type": "response", "request_id": request_id, "ok": True, "result": result}
        except CommandRejected as exc:
            response = {
                "type": "response",
                "request_id": request_id,
                "ok": False,
                "status": exc.status,
                "error": exc.message,
            }
        except Exception:
            response = {
                "type": "response",
                "request_id": request_id,
                "ok": False,
                "status": 500,
                "error": "WebRTC request failed",
            }
        if channel is not None and str(getattr(channel, "readyState", "")) == "open":
            channel.send(json.dumps(response, separators=(",", ":"), ensure_ascii=True, default=str))

    async def _send_session_state(self, session: WebRtcSession, *, force: bool) -> dict[str, Any]:
        state = await self.processor.remote_state(session.token)
        snapshot = session.revision.snapshot(state)
        if force or int(snapshot["revision"]) != session.last_sent_revision:
            channel = session.channel
            if channel is not None and str(getattr(channel, "readyState", "")) == "open":
                channel.send(json.dumps({"type": "state", "state": snapshot}, separators=(",", ":"), ensure_ascii=True, default=str))
                session.last_sent_revision = int(snapshot["revision"])
        return snapshot

    async def _replace_device_sessions(self, device_id: str) -> None:
        async with self._lock:
            existing = [
                session.session_id
                for session in self._sessions.values()
                if session.device_id == device_id
            ]
        for session_id in existing:
            await self.close(session_id, device_id=device_id)

    async def _prune(self) -> None:
        now = time.monotonic()
        stale = [
            session.session_id
            for session in self._sessions.values()
            if session.closed
            or now - session.created_at > self.session_ttl_seconds
            or now - session.updated_at > self.session_ttl_seconds
        ]
        for session_id in stale:
            await self.close(session_id)

    async def _enforce_session_limit(self) -> None:
        async with self._lock:
            overflow = sorted(
                self._sessions.values(), key=lambda session: session.updated_at
            )[: max(0, len(self._sessions) - self.max_sessions)]
            for session in overflow:
                self._sessions.pop(session.session_id, None)
        for session in overflow:
            await self._close_session(session)

    @staticmethod
    def _aiortc():
        activate_host_webrtc_layer()
        try:
            import av  # noqa: F401
            import pylibsrtp  # noqa: F401
            from aiortc import (  # type: ignore
                RTCConfiguration,
                RTCIceServer,
                RTCPeerConnection,
                RTCSessionDescription,
            )
        except Exception as exc:
            raise WebRtcUnavailable("aiortc is not installed") from exc
        return RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
