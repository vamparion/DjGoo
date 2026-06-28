from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


DEFAULT_MCP_URL = "http://127.0.0.1:8800/mcp"
MAX_TRACK_SECONDS = 10 * 60
BAD_TITLE_RE = re.compile(
    r"\b("
    r"instrumental|karaoke|reaction|interview|lesson|tutorial|similarit(?:y|ies)|"
    r"documentary|shorts?|clip|compilation|playlist|full album|greatest hits|"
    r"mix|dj set|hours? of|live at|live from|live in"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NuclearTrack:
    title: str
    artists: List[str]
    duration_seconds: int = 0

    def redbot_query(self) -> str:
        artist_text = ", ".join(self.artists)
        if artist_text:
            return f"{artist_text} - {self.title} official audio"
        return f"{self.title} official audio"


def normalize_nuclear_track(data: Dict[str, Any]) -> NuclearTrack:
    artists = [
        str(item.get("name", "")).strip()
        for item in data.get("artists", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    duration_ms = data.get("durationMs") or 0
    try:
        duration_seconds = int(float(duration_ms) / 1000)
    except (TypeError, ValueError):
        duration_seconds = 0
    return NuclearTrack(
        title=str(data.get("title", "")).strip(),
        artists=artists,
        duration_seconds=duration_seconds,
    )


class NuclearResolver:
    def __init__(
        self,
        *,
        mcp_url: str = DEFAULT_MCP_URL,
        timeout_seconds: float = 5.0,
        transport: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.mcp_url = mcp_url
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self._session_id: Optional[str] = None

    def resolve_track_query(self, query: str) -> Optional[str]:
        result = self._call(
            "Metadata.search",
            {"params": {"query": query, "types": ["tracks"], "limit": 8}},
        )
        for item in result.get("tracks", []) or []:
            track = normalize_nuclear_track(item)
            if self.accepts_track(track):
                return track.redbot_query()
        return None

    def resolve_album_queries(self, query: str, *, limit: int = 50) -> List[str]:
        result = self._call(
            "Metadata.search",
            {"params": {"query": query, "types": ["albums"], "limit": 5}},
        )
        albums = result.get("albums", []) or []
        if not albums:
            return []
        album = albums[0]
        source = album.get("source", {}) if isinstance(album, dict) else {}
        album_id = str(source.get("id", "")).strip()
        provider_id = str(source.get("provider", "")).strip()
        if not album_id:
            return []
        details = self._call(
            "Metadata.fetchAlbumDetails",
            {"albumId": album_id, "providerId": provider_id or None},
        )
        queries = []
        for item in details.get("tracks", []) or []:
            track = normalize_nuclear_track(item)
            if self.accepts_track(track):
                queries.append(track.redbot_query())
            if len(queries) >= limit:
                break
        return queries

    def accepts_track(self, track: NuclearTrack) -> bool:
        if not track.title:
            return False
        if track.duration_seconds and track.duration_seconds > MAX_TRACK_SECONDS:
            return False
        return BAD_TITLE_RE.search(track.title) is None

    def _call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if self._transport is not None:
            return self._transport(method, params)
        try:
            return self._mcp_call(method, params)
        except (OSError, TimeoutError, urllib.error.URLError, ValueError, KeyError):
            return {}

    def _mcp_call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "id": method,
            "method": "tools/call",
            "params": {
                "name": "call",
                "arguments": {
                    "method": method,
                    "params": params,
                },
            },
        }
        response = self._post(payload, session_required=True)
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        return data if isinstance(data, dict) else {}

    def _ensure_session(self) -> None:
        if self._session_id:
            return
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": "initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "djgoo", "version": "0.1"},
                },
            },
            session_required=False,
        )
        self._session_id = str(response.get("_session_id", "")).strip()
        if self._session_id:
            self._post(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                session_required=True,
            )

    def _post(self, payload: Dict[str, Any], *, session_required: bool) -> Dict[str, Any]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_required and self._session_id:
            headers["mcp-session-id"] = self._session_id
        request = urllib.request.Request(
            self.mcp_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            data = _parse_sse_json(body)
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                data["_session_id"] = session_id
            return data


def _parse_sse_json(body: str) -> Dict[str, Any]:
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or not data.startswith("{"):
            continue
        parsed = json.loads(data)
        if isinstance(parsed, dict):
            return parsed
    return {}
