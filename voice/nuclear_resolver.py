from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from voice.operational_log import log_event


DEFAULT_MCP_URL = "http://127.0.0.1:8800/mcp"
MAX_TRACK_SECONDS = 10 * 60
BAD_TITLE_RE = re.compile(
    r"\b("
    r"instrumental|karaoke|reaction|interview|lesson|tutorial|similarit(?:y|ies)|"
    r"documentary|shorts?|clip|compilation|playlist|full album|greatest hits|"
    r"mix|dj set|hours? of|live at|live from|live in|extended version|loop|repeat"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NuclearTrack:
    title: str
    artists: List[str]
    duration_seconds: int = 0
    isrc: str = ""

    def redbot_query(self) -> str:
        artist_text = ", ".join(self.artists)
        identifier = f' "{self.isrc}"' if self.isrc else ""
        if artist_text:
            return f"{artist_text} - {self.title}{identifier} official audio"
        return f"{self.title}{identifier} official audio"


def normalize_nuclear_track(data: Dict[str, Any]) -> NuclearTrack:
    artists = [
        str(item.get("name", "")).strip()
        for item in data.get("artists", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    duration_ms = data.get("durationMs") or data.get("duration_ms") or 0
    try:
        duration_seconds = int(float(duration_ms) / 1000)
    except (TypeError, ValueError):
        duration_seconds = 0
    source = data.get("source", {}) if isinstance(data.get("source"), dict) else {}
    isrc = str(data.get("isrc") or source.get("isrc") or "").strip().upper()
    return NuclearTrack(
        title=str(data.get("title", "")).strip(),
        artists=artists,
        duration_seconds=duration_seconds,
        isrc=isrc,
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

    def resolve_track(self, query: str) -> Optional[NuclearTrack]:
        log_event("nuclear.track.resolve.start", query=query, mcp_url=self.mcp_url)
        result = self._call(
            "Metadata.search",
            {"params": {"query": query, "types": ["tracks"], "limit": 10}},
        )
        tracks = result.get("tracks", []) or []
        log_event("nuclear.track.search.result", query=query, count=len(tracks))
        for index, item in enumerate(tracks):
            if not isinstance(item, dict):
                continue
            track = normalize_nuclear_track(item)
            if self.accepts_track(track):
                log_event(
                    "nuclear.track.accepted",
                    query=query,
                    index=index,
                    title=track.title,
                    artists=track.artists,
                    duration_seconds=track.duration_seconds,
                    isrc=track.isrc,
                )
                return track
            log_event(
                "nuclear.track.rejected",
                query=query,
                index=index,
                title=track.title,
                artists=track.artists,
                duration_seconds=track.duration_seconds,
                isrc=track.isrc,
            )
        log_event("nuclear.track.resolve.empty", query=query)
        return None

    def resolve_track_candidates(self, query: str, *, limit: int = 8) -> List[NuclearTrack]:
        result = self._call(
            "Metadata.search",
            {"params": {"query": query, "types": ["tracks"], "limit": max(1, limit)}},
        )
        candidates: List[NuclearTrack] = []
        for item in result.get("tracks", []) or []:
            if not isinstance(item, dict):
                continue
            track = normalize_nuclear_track(item)
            if self.accepts_track(track):
                candidates.append(track)
            if len(candidates) >= limit:
                break
        return candidates

    def resolve_track_query(self, query: str) -> Optional[str]:
        track = self.resolve_track(query)
        if track is None:
            return None
        resolved = track.redbot_query()
        log_event("nuclear.track.query", query=query, resolved_query=resolved)
        return resolved

    def resolve_album_queries(self, query: str, *, limit: int = 50) -> List[str]:
        log_event("nuclear.album.resolve.start", query=query, limit=limit)
        result = self._call(
            "Metadata.search",
            {"params": {"query": query, "types": ["albums"], "limit": 5}},
        )
        albums = result.get("albums", []) or []
        log_event("nuclear.album.search.result", query=query, count=len(albums))
        if not albums:
            return []
        album = albums[0]
        source = album.get("source", {}) if isinstance(album, dict) else {}
        album_id = str(source.get("id", "")).strip()
        provider_id = str(source.get("provider", "")).strip()
        if not album_id:
            log_event("nuclear.album.missing_id", query=query)
            return []
        details = self._call(
            "Metadata.fetchAlbumDetails",
            {"albumId": album_id, "providerId": provider_id or None},
        )
        queries = []
        for item in details.get("tracks", []) or []:
            if not isinstance(item, dict):
                continue
            track = normalize_nuclear_track(item)
            if self.accepts_track(track):
                queries.append(track.redbot_query())
            if len(queries) >= limit:
                break
        log_event("nuclear.album.resolve.done", query=query, queued_count=len(queries), album_id=album_id)
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
        except (OSError, TimeoutError, urllib.error.URLError, ValueError, KeyError) as exc:
            log_event("nuclear.mcp.call.failed", method=method, error=type(exc).__name__, detail=str(exc))
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
                    "clientInfo": {"name": "djgoo", "version": "0.2"},
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
