import { useEffect, useState } from "react";
import { ListPlus, Plus, Trash2 } from "lucide-react";
import { playlistAction } from "../api";
import type { PanelProps } from "./types";

type Props = PanelProps & { compact?: boolean; expanded?: boolean; canManage?: boolean; refresh?: () => Promise<unknown> };

export function PlaylistPanel({ state, send, compact = false, expanded = false, canManage = false, refresh }: Props) {
  const [name, setName] = useState(state.playlists[0]?.name || "");
  const [drag, setDrag] = useState("");
  const [bulk, setBulk] = useState("");
  const playlist = state.playlists.find((item) => item.name === name) || state.playlists[0];
  useEffect(() => { if (!name && state.playlists[0]) setName(state.playlists[0].name); }, [name, state.playlists]);
  async function action(kind: string, payload: Record<string, unknown> = {}) { if (!playlist) return; await playlistAction(kind, { playlist: playlist.name, ...payload }); await send("queue"); }
  async function addHistory(trackId: string, playlistName: string) { if (!trackId || !playlistName) return; await playlistAction("history-add", { playlist: playlistName, track_id: trackId }); await refresh?.(); }
  async function addDroppedTrack(raw: string, playlistName: string) { if (!raw || !playlistName) return; const track = JSON.parse(raw); await playlistAction("import", { playlist: playlistName, tracks: [track] }); await refresh?.(); }
  async function createPlaylist(trackId = "") {
    const requested = window.prompt("New playlist name", "");
    if (!requested?.trim()) return;
    await playlistAction("create", { playlist: requested.trim() });
    if (trackId) await playlistAction("history-add", { playlist: requested.trim(), track_id: trackId });
    setName(requested.trim());
    await refresh?.();
  }
  async function deletePlaylist() {
    if (!playlist || !window.confirm(`Delete "${playlist.name}" and all ${playlist.track_count} saved tracks? This cannot be undone.`)) return;
    const currentIndex = state.playlists.findIndex((item) => item.name === playlist.name);
    const next = state.playlists[currentIndex + 1] || state.playlists[currentIndex - 1];
    await action("delete");
    setName(next?.name || "");
  }
  async function drop(beforeId: string) { if (!playlist || !drag || drag === beforeId) return; const ids = playlist.tracks.map((track) => track.id || "").filter(Boolean); const from = ids.indexOf(drag); const to = ids.indexOf(beforeId); ids.splice(to, 0, ids.splice(from, 1)[0]); setDrag(""); await action("reorder", { track_ids: ids }); }
  if (compact) return <section className="panel playlist-dock"><div className="panel-title-row"><div><h2>Playlists</h2><p>Drop songs here.</p></div>{canManage && <button className="icon-button" title="Create playlist" aria-label="Create playlist" onClick={() => void createPlaylist()}><Plus size={18} /></button>}</div><div className="list playlist-drop-list">{state.playlists.slice(0, 8).map((item) => <div className="row playlist-drop-row" key={item.name} onDragOver={(event) => { if (canManage) event.preventDefault(); }} onDrop={(event) => { const historyId = event.dataTransfer.getData("text/djgoo-history"); if (historyId) void addHistory(historyId, item.name); else void addDroppedTrack(event.dataTransfer.getData("application/djgoo-track"), item.name); }}><ListPlus size={16} /><div><strong>{item.name}</strong><span>{item.track_count} tracks</span></div><button className="btn" onClick={() => void send("play_playlist", { playlist: item.name })}>Play</button></div>)}{canManage && <button className="new-playlist-drop" onClick={() => void createPlaylist()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => void createPlaylist(event.dataTransfer.getData("text/djgoo-history"))}><Plus size={18} /><span>New playlist</span></button>}</div></section>;
  return <section className={`panel ${expanded ? "wide-panel" : ""}`}>
    <div className="panel-title-row"><div><h2>Playlists</h2><p>Choose a playlist, add songs, then drag them into the order you want.</p></div>{playlist && <div className="inline-actions">{canManage && <button className="btn danger icon-action" title="Delete playlist" aria-label={`Delete ${playlist.name}`} onClick={() => void deletePlaylist()}><Trash2 size={16} /><span>Delete</span></button>}<button className="btn" onClick={() => void action("cleanup")}>Remove duplicates</button><button className="btn primary" onClick={() => void send("play_playlist", { playlist: playlist.name })}>Play</button></div>}</div>
    <div className="playlist-selector"><label>Playlist<select value={playlist?.name || ""} onChange={(event) => setName(event.target.value)}>{state.playlists.map((item) => <option key={item.name}>{item.name}</option>)}</select></label>{playlist && <span>{playlist.track_count} tracks</span>}</div>
    {expanded && playlist && <div className="playlist-tools">
      <section className="subpanel"><h3>Add from history</h3><div className="inline-actions"><button className="btn" onClick={() => void action("from-history", { seconds: 3600 })}>Add last hour</button><button className="btn" onClick={() => void action("from-history", { seconds: 43200 })}>Add tonight</button></div></section>
      <details className="subpanel"><summary>Add a pasted list</summary><textarea value={bulk} onChange={(event) => setBulk(event.target.value)} placeholder="One song title or URL per line" />{bulk.trim() && <div className="import-summary"><strong>{bulk.split(/\n/).filter((line) => line.trim()).length} songs ready</strong><button className="btn primary" onClick={() => void action("import", { tracks: bulk.split(/\n/).filter((line) => line.trim()).map((line) => ({ title: line.trim(), uri: line.trim().startsWith("http") ? line.trim() : "" })) }).then(() => setBulk(""))}>Add to playlist</button></div>}</details>
      <details className="subpanel playlist-details"><summary>Playlist details</summary><div className="editor-row"><input defaultValue={playlist.folder} placeholder="Folder" onBlur={(event) => void action("metadata", { metadata: { folder: event.target.value } })} /><input defaultValue={(playlist.tags || []).join(", ")} placeholder="Tags" onBlur={(event) => void action("metadata", { metadata: { tags: event.target.value.split(",") } })} /></div><div className="editor-row"><input defaultValue={playlist.artwork_url} placeholder="Artwork URL" onBlur={(event) => void action("metadata", { metadata: { artwork_url: event.target.value } })} /><input defaultValue={playlist.smart_query} placeholder="Smart playlist rule" onBlur={(event) => void action("metadata", { metadata: { smart_query: event.target.value } })} /></div><textarea defaultValue={playlist.description} placeholder="Description" onBlur={(event) => void action("metadata", { metadata: { description: event.target.value } })} /></details>
    </div>}
    {playlist && <h3 className="track-list-heading">Songs <span>{playlist.track_count}</span></h3>}
    <div className="list draggable-list">{playlist?.tracks.map((track, index) => <div className="row playlist-track-row" draggable key={track.id} onDragStart={() => setDrag(track.id || "")} onDragOver={(event) => event.preventDefault()} onDrop={() => void drop(track.id || "")}><div className="drag-handle">⋮⋮</div><div><strong>{track.title}</strong><span>{track.artist || `Track ${index + 1}`}</span></div><div className="inline-actions"><button className="btn" onClick={() => { const uri = window.prompt("Replacement song URL", track.uri || ""); if (uri) void action("replace", { track_id: track.id, replacement: { ...track, uri } }); }}>Replace source</button><button className="btn danger" onClick={() => void action("remove", { track_ids: [track.id] })}>Remove</button></div></div>)}{!playlist && <div className="empty-state"><strong>No playlists yet</strong><p>Create one from the Mini Player, then organize it here.</p></div>}</div>
  </section>;
}
