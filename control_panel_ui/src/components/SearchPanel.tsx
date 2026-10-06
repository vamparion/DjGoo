import { useState, type DragEvent } from "react";
import { ListPlus, Play, Radio, Search } from "lucide-react";
import { playlistAction, searchLibrary, searchMusic, type MusicSearchResult } from "../api";
import { clearDraggedTrack, rememberDraggedTrack } from "../trackDrag";
import type { PanelProps } from "./types";
import { normalizeMediaInput } from "../mediaInput";

function duration(seconds: number) {
  if (!seconds) return "";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function SearchPanel({ state, send }: PanelProps) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState<MusicSearchResult[]>([]);
  const [library, setLibrary] = useState<Array<Record<string, unknown>>>([]);

  async function search() {
    const q = normalizeMediaInput(query);
    if (!q) return;
    setBusy(true); setError(""); setLibrary([]);
    try {
      const data = await searchMusic(q);
      setResults(data.results || []); setSearched(true);
    } catch (err) {
      setError(String((err as Error).message || err)); setResults([]); setSearched(true);
    } finally { setBusy(false); }
  }

  async function findEverywhere() {
    const q = normalizeMediaInput(query);
    if (!q) return;
    setBusy(true); setError(""); setResults([]);
    try {
      const data = await searchLibrary(q);
      setLibrary(data.results); setSearched(true);
    } catch (err) { setError(String((err as Error).message || err)); }
    finally { setBusy(false); }
  }

  function dragTrack(event: DragEvent, track: MusicSearchResult) {
    rememberDraggedTrack(track);
    event.dataTransfer.setData("application/djgoo-track", JSON.stringify(track));
    event.dataTransfer.setData("text/plain", JSON.stringify(track));
    event.dataTransfer.effectAllowed = "copy";
  }

  async function addTo(destination: string, track: MusicSearchResult) {
    if (!destination) return;
    if (destination === "queue") await send("play_next", { query: track.uri });
    else await playlistAction("import", { playlist: destination, tracks: [track] });
  }

  return (
    <section className="panel search-panel">
      <div className="panel-title-row"><div><h2>Find Music</h2><p>Browse matching songs first. Nothing plays until you choose a result.</p></div></div>
      <div className="search-command">
        <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="Song title, lyric fragment, artist, or album" autoFocus />
        <button className="btn primary icon-action" onClick={() => void search()} disabled={busy || !query.trim()}><Search size={16} /><span>{busy ? "Searching" : "Search"}</span></button>
        <button className="btn" onClick={() => void findEverywhere()} disabled={busy || !query.trim()}>My Library</button>
      </div>
      {error && <div className="banner error search-error">{error}</div>}
      <div className="search-results" aria-live="polite">
        {results.map((track) => <div className="search-result" draggable key={track.id || track.uri} onDragStart={(event) => dragTrack(event, track)} onDragEnd={() => window.setTimeout(clearDraggedTrack, 0)}>
          {track.artwork_url ? <img src={track.artwork_url} alt="" /> : <div className="search-art-placeholder"><Search size={18} /></div>}
          <div className="search-result-copy"><strong>{track.title}</strong><span>{track.artist || "Unknown artist"}{track.duration_seconds ? ` · ${duration(track.duration_seconds)}` : ""}</span></div>
          <div className="inline-actions">
            <button className="btn primary icon-action" title="Play now" onClick={() => void send("play", { query: track.uri })}><Play size={15} /><span>Now</span></button>
            <button className="btn icon-action" title="Add next" onClick={() => void send("play_next", { query: track.uri })}><ListPlus size={15} /><span>Next</span></button>
            <button className="btn amber icon-action" title="Start radio from this song" onClick={() => void send("start_radio", { query: track.uri })}><Radio size={15} /><span>Radio</span></button>
            <select className="result-destination" aria-label={`Add ${track.title} to queue or playlist`} defaultValue="" onChange={(event) => { const value = event.target.value; event.target.value = ""; void addTo(value, track); }}><option value="" disabled>Add to...</option><option value="queue">Queue</option>{state.playlists.map((playlist) => <option key={playlist.name} value={playlist.name}>{playlist.name}</option>)}</select>
          </div>
        </div>)}
        {library.map((item, index) => <div className="search-result" key={`${String(item.uri)}-${index}`}><div className="search-art-placeholder"><Search size={18} /></div><div className="search-result-copy"><strong>{String(item.title || "Untitled")}</strong><span>{String(item.kind)} · {String(item.group)}</span></div><button className="btn icon-action" onClick={() => void send("play_next", { query: String(item.uri || item.title) })}><ListPlus size={15} /><span>Next</span></button></div>)}
        {searched && !busy && !error && results.length === 0 && library.length === 0 && <div className="empty-state"><strong>No matching songs found</strong><p>Try fewer words, an artist name, or a lyric fragment.</p></div>}
      </div>
    </section>
  );
}
