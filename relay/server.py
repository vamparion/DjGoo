from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from aiohttp import WSMsgType, web

from voice.relay_crypto import verify_host_hello


MAX_MESSAGE_BYTES = 64 * 1024
MAX_CLIENT_MESSAGES = 30
CLIENT_RATE_WINDOW_SECONDS = 10.0
HOST_HELLO_TIMEOUT_SECONDS = 10.0
STALE_ROUTE_SECONDS = 90.0


@dataclass
class ClientRoute:
    websocket: web.WebSocketResponse
    room_id: str
    created_at: float


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = int(limit)
        self.window_seconds = float(window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        return True


class RelayState:
    def __init__(self) -> None:
        self.hosts: dict[str, web.WebSocketResponse] = {}
        self.clients: dict[str, ClientRoute] = {}
        self.host_lock = asyncio.Lock()
        self.client_lock = asyncio.Lock()
        self.client_limiter = SlidingWindowLimiter(MAX_CLIENT_MESSAGES, CLIENT_RATE_WINDOW_SECONDS)
        self.seen_host_nonces: dict[str, float] = {}

    async def register_host(self, room_id: str, websocket: web.WebSocketResponse) -> bool:
        async with self.host_lock:
            existing = self.hosts.get(room_id)
            if existing is not None and not existing.closed:
                return False
            self.hosts[room_id] = websocket
            return True

    async def unregister_host(self, room_id: str, websocket: web.WebSocketResponse) -> None:
        async with self.host_lock:
            if self.hosts.get(room_id) is websocket:
                self.hosts.pop(room_id, None)

    async def get_host(self, room_id: str) -> web.WebSocketResponse | None:
        async with self.host_lock:
            websocket = self.hosts.get(room_id)
            if websocket is None or websocket.closed:
                self.hosts.pop(room_id, None)
                return None
            return websocket

    async def register_client(self, route_id: str, route: ClientRoute) -> None:
        async with self.client_lock:
            self.clients[route_id] = route

    async def pop_client(self, route_id: str) -> ClientRoute | None:
        async with self.client_lock:
            return self.clients.pop(route_id, None)

    async def remove_websocket_routes(self, websocket: web.WebSocketResponse) -> None:
        async with self.client_lock:
            stale = [route_id for route_id, route in self.clients.items() if route.websocket is websocket]
            for route_id in stale:
                self.clients.pop(route_id, None)

    def claim_host_nonce(self, room_id: str, nonce: str) -> bool:
        now = time.monotonic()
        for key, timestamp in list(self.seen_host_nonces.items()):
            if now - timestamp > 120:
                self.seen_host_nonces.pop(key, None)
        key = f"{room_id}:{nonce}"
        if key in self.seen_host_nonces:
            return False
        self.seen_host_nonces[key] = now
        return True


STATE_KEY: web.AppKey[RelayState] = web.AppKey("relay_state", RelayState)
CLEANUP_TASK_KEY: web.AppKey[asyncio.Task] = web.AppKey("cleanup_task", asyncio.Task)


def relay_state(request: web.Request) -> RelayState:
    return request.app[STATE_KEY]


@web.middleware
async def secure_transport(request: web.Request, handler):
    allow_insecure = os.environ.get("DJGOO_RELAY_ALLOW_INSECURE", "").strip() == "1"
    trust_proxy = os.environ.get("DJGOO_RELAY_TRUST_PROXY", "").strip() == "1"
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    is_secure = request.secure or (trust_proxy and forwarded_proto == "https")
    if request.path != "/healthz" and not allow_insecure and not is_secure:
        raise web.HTTPUpgradeRequired(text="DjGoo Relay requires TLS termination")
    return await handler(request)


async def health(request: web.Request) -> web.Response:
    state = relay_state(request)
    return web.json_response(
        {
            "service": "djgoo-relay",
            "status": "ok",
            "protocol": 1,
            "connected_hosts": len(state.hosts),
            "pending_routes": len(state.clients),
        }
    )


async def host_socket(request: web.Request) -> web.WebSocketResponse:
    state = relay_state(request)
    websocket = web.WebSocketResponse(
        heartbeat=25,
        receive_timeout=60,
        max_msg_size=MAX_MESSAGE_BYTES,
        compress=False,
    )
    await websocket.prepare(request)
    room_id = ""
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=HOST_HELLO_TIMEOUT_SECONDS)
        if message.type != WSMsgType.TEXT:
            await websocket.close(code=4000, message=b"host hello required")
            return websocket
        try:
            hello = json.loads(message.data)
            if not isinstance(hello, dict):
                raise ValueError
            room_id = verify_host_hello(hello, now=int(time.time()))
        except (json.JSONDecodeError, ValueError):
            await websocket.close(code=4001, message=b"invalid host hello")
            return websocket
        if not state.claim_host_nonce(room_id, str(hello.get("nonce") or "")):
            await websocket.close(code=4002, message=b"replayed host hello")
            return websocket
        if not await state.register_host(room_id, websocket):
            await websocket.close(code=4003, message=b"room already has an active host")
            return websocket

        await websocket.send_json({"type": "host_ready", "protocol": 1, "room_id": room_id})
        async for message in websocket:
            if message.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(message.data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict) or payload.get("type") != "relay_response":
                    continue
                route_id = str(payload.get("route_id") or "")
                envelope = payload.get("envelope")
                if not route_id or not isinstance(envelope, dict):
                    continue
                route = await state.pop_client(route_id)
                if route is None or route.room_id != room_id:
                    continue
                if time.monotonic() - route.created_at > STALE_ROUTE_SECONDS:
                    continue
                if not route.websocket.closed:
                    await route.websocket.send_json(
                        {"type": "relay_response", "route_id": route_id, "envelope": envelope}
                    )
            elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED}:
                break
    finally:
        if room_id:
            await state.unregister_host(room_id, websocket)
    return websocket


async def client_socket(request: web.Request) -> web.WebSocketResponse:
    state = relay_state(request)
    room_id = request.match_info.get("room_id", "").strip()
    if not room_id or len(room_id) > 64:
        raise web.HTTPBadRequest(text="Invalid relay room")

    websocket = web.WebSocketResponse(
        heartbeat=25,
        receive_timeout=90,
        max_msg_size=MAX_MESSAGE_BYTES,
        compress=False,
    )
    await websocket.prepare(request)
    remote_key = request.remote or "unknown"
    try:
        async for message in websocket:
            if message.type == WSMsgType.TEXT:
                if not state.client_limiter.allow(remote_key):
                    await websocket.send_json({"type": "error", "code": "rate_limited"})
                    continue
                try:
                    payload = json.loads(message.data)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "code": "invalid_json"})
                    continue
                envelope = payload.get("envelope") if isinstance(payload, dict) else None
                if not isinstance(envelope, dict) or str(envelope.get("room_id") or "") != room_id:
                    await websocket.send_json({"type": "error", "code": "invalid_envelope"})
                    continue
                host = await state.get_host(room_id)
                if host is None:
                    await websocket.send_json({"type": "error", "code": "host_offline"})
                    continue
                route_id = secrets.token_urlsafe(18)
                await state.register_client(
                    route_id,
                    ClientRoute(websocket=websocket, room_id=room_id, created_at=time.monotonic()),
                )
                try:
                    await host.send_json(
                        {"type": "relay_request", "route_id": route_id, "envelope": envelope}
                    )
                except (ConnectionError, RuntimeError):
                    await state.pop_client(route_id)
                    await websocket.send_json({"type": "error", "code": "host_disconnected"})
            elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED}:
                break
    finally:
        await state.remove_websocket_routes(websocket)
    return websocket


async def cleanup_routes(app: web.Application) -> None:
    state = app[STATE_KEY]
    while True:
        await asyncio.sleep(15)
        now = time.monotonic()
        async with state.client_lock:
            stale = [
                route_id
                for route_id, route in state.clients.items()
                if route.websocket.closed or now - route.created_at > STALE_ROUTE_SECONDS
            ]
            for route_id in stale:
                state.clients.pop(route_id, None)


async def start_background_tasks(app: web.Application) -> None:
    app[CLEANUP_TASK_KEY] = asyncio.create_task(cleanup_routes(app))


async def stop_background_tasks(app: web.Application) -> None:
    task = app.get(CLEANUP_TASK_KEY)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_application() -> web.Application:
    app = web.Application(middlewares=[secure_transport], client_max_size=MAX_MESSAGE_BYTES)
    app[STATE_KEY] = RelayState()
    app.router.add_get("/healthz", health)
    app.router.add_get("/v1/host", host_socket)
    app.router.add_get("/v1/client/{room_id}", client_socket)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(stop_background_tasks)
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the transport-only DjGoo relay.")
    parser.add_argument("--host", default=os.environ.get("DJGOO_RELAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DJGOO_RELAY_PORT", "8080")))
    args = parser.parse_args()
    web.run_app(create_application(), host=args.host, port=args.port, access_log=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
