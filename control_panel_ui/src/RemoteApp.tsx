import { useEffect, useRef, useState } from "react";
import { Ban, ChevronRight, Heart, ListMusic, Pause, Play, Radio, RefreshCw, Search, SkipForward, Sparkles, ThumbsDown, Volume2 } from "lucide-react";
import { pairWeb, remoteCommand, remoteState, type WebCredential } from "./remoteTransport";

const SESSION_KEY = "djgoo-web-session";
const REMEMBER_KEY = "djgoo-web-remembered";

type RemoteTrack = { id?: string; title?: string; artist?: string; requester?: string; request_type?: string; duration?: string };
type RemoteState = {
  generated_at?: number;
  playback?: { title?: string; artist?: string; station?: string; remaining?: string; queue_count?: number; requester?: string; state?: string };
  queue?: RemoteTrack[];
  session?: { role?: string; display_name?: string };
};

export function RemoteApp({ invite }: { invite: string }) {
  const [credential, setCredential] = useState<WebCredential | null>(() => JSON.parse(sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(REMEMBER_KEY) || "null"));
  const [state, setState] = useState<RemoteState | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState("");
  const [requestMode, setRequestMode] = useState<"play_now" | "play" | "queue_request">("play");
  const refreshing = useRef(false);
  async function refresh() { if (!credential || refreshing.current) return; refreshing.current = true; try { setState(await remoteState(credential)); setError(""); } catch (e) { setError(String((e as Error).message)); } finally { refreshing.current = false; } }
  useEffect(() => { if (!credential) return; void refresh(); let timer = 0; const schedule = () => { clearInterval(timer); if (!document.hidden) timer = window.setInterval(refresh, 15000); }; document.addEventListener("visibilitychange", schedule); schedule(); return () => { clearInterval(timer); document.removeEventListener("visibilitychange", schedule); }; }, [credential]);
  async function connect() { try { const paired = await pairWeb(invite, navigator.userAgent.includes("Mobile") ? "DjGoo Web Mobile" : "DjGoo Web Browser"); setCredential(paired.credential); sessionStorage.setItem(SESSION_KEY, JSON.stringify(paired.credential)); if (remember) localStorage.setItem(REMEMBER_KEY, JSON.stringify(paired.credential)); } catch (e) { setError(String((e as Error).message)); } }
  async function command(intent: string, values: Record<string, unknown> = {}) {
    if (!credential || busy) return;
    setBusy(intent); setError("");
    try { await remoteCommand(credential, intent, values); await refresh(); }
    catch (e) { setError(String((e as Error).message)); }
    finally { setBusy(""); }
  }
  if (!credential) return <main className="remote-shell remote-pairing"><section className="remote-pair"><div className="remote-brand-mark"><img src="./djgoo-mark.svg" alt=""/></div><span className="remote-kicker">PRIVATE PLAYER ACCESS</span><h1>Connect to DjGoo</h1><p>Control the live Discord music session from this device.</p><label><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)}/> Remember this device</label><button className="remote-primary" onClick={connect}>Connect securely <ChevronRight size={18}/></button>{error && <p className="remote-error">{error}</p>}</section></main>;

  const playback = state?.playback || {};
  const queue = state?.queue || [];
  const isPaused = String(playback.state || "").toLowerCase().includes("pause");
  const radioActive = Boolean(playback.station);
  const updated = state?.generated_at ? new Date(state.generated_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "Connecting";
  const submitRequest = () => {
    const value = query.trim();
    if (!value) return;
    void command(requestMode, { query: value, raw: value });
    setQuery("");
  };

  return <main className="remote-shell">
    <header className="remote-header">
      <div className="remote-brand"><div className="remote-brand-mark"><img src="./djgoo-mark.svg" alt=""/></div><div><strong>DjGoo</strong><small>{state?.session?.display_name || "Game session"} · {state?.session?.role || "remote"}</small></div></div>
      <button className="remote-icon-button" onClick={refresh} aria-label="Refresh" title="Refresh"><RefreshCw size={18}/></button>
    </header>
    {error && <div className="remote-alert">{error}</div>}
    <section className="remote-player">
      <div className={`remote-art ${playback.title ? "is-playing" : ""}`}><Radio size={34}/><span>{radioActive ? "RADIO" : playback.title ? "LIVE" : "IDLE"}</span></div>
      <div className="remote-track-copy"><span className="remote-kicker">{playback.state || "READY"}</span><h1>{playback.title || "Ready for a song"}</h1><p>{playback.artist || "DjGoo is standing by"}</p><div className="remote-track-meta">{radioActive && <span><Radio size={13}/>{playback.station}</span>} {playback.remaining && <span>{playback.remaining}</span>} {playback.requester && <span>Requested by {playback.requester}</span>}</div></div>
    </section>
    <section className="remote-transport" aria-label="Playback controls">
      <button onClick={() => command("volume_down")} disabled={Boolean(busy)}><Volume2 size={18}/><span>Vol -</span></button>
      <button className="remote-play" onClick={() => command(isPaused ? "resume" : "pause")} disabled={Boolean(busy)}>{isPaused ? <Play size={24} fill="currentColor"/> : <Pause size={24} fill="currentColor"/>}<span>{isPaused ? "Resume" : "Pause"}</span></button>
      <button onClick={() => command("skip")} disabled={Boolean(busy)}><SkipForward size={21}/><span>Skip</span></button>
    </section>
    {radioActive && <section className="remote-radio-strip"><div><span className="remote-kicker">ACTIVE STATION</span><strong>{playback.station}</strong></div><button onClick={() => command("stop_radio")} disabled={Boolean(busy)}>Stop Radio</button></section>}
    <section className="remote-feedback" aria-label="Radio feedback">
      <button onClick={() => command("station_like_current")} disabled={!radioActive || Boolean(busy)}><Heart size={18}/><span>Like</span></button>
      <button onClick={() => command("station_more_like_current")} disabled={!radioActive || Boolean(busy)}><Sparkles size={18}/><span>More like</span></button>
      <button onClick={() => command("station_less_like_current")} disabled={!radioActive || Boolean(busy)}><ThumbsDown size={18}/><span>Less like</span></button>
      <button onClick={() => command("station_ban_current")} disabled={!radioActive || Boolean(busy)}><Ban size={18}/><span>Ban</span></button>
    </section>
    <section className="remote-request">
      <div className="remote-section-title"><div><span className="remote-kicker">QUICK REQUEST</span><h2>Find the next track</h2></div><Search size={19}/></div>
      <form onSubmit={e => { e.preventDefault(); submitRequest(); }}><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Song, artist, album, or URL" maxLength={500}/><button className="remote-primary" disabled={!query.trim() || Boolean(busy)}>{busy === requestMode ? "Sending" : "Request"}</button></form>
      <div className="remote-segments" role="group" aria-label="Request timing">{([['play_now','Now'],['play','Next'],['queue_request','Later']] as const).map(([value,label]) => <button type="button" className={requestMode === value ? "active" : ""} onClick={() => setRequestMode(value)} key={value}>{label}</button>)}</div>
    </section>
    <section className="remote-queue">
      <div className="remote-section-title"><div><span className="remote-kicker">UP NEXT</span><h2>Queue <b>{queue.length}</b></h2></div><ListMusic size={20}/></div>
      {queue.length ? <div className="remote-queue-list">{queue.map((track, index) => <div className="remote-queue-row" key={track.id || `${track.title}-${index}`}><span className="remote-queue-number">{index + 1}</span><div><strong>{track.title || "Untitled track"}</strong><span>{track.artist || track.requester || (track.request_type === "radio" ? "DjGoo radio" : "DjGoo selection")}</span></div>{track.request_type === "radio" && <em>RADIO</em>}</div>)}</div> : <div className="remote-empty"><ListMusic size={24}/><span>The queue is clear.</span></div>}
    </section>
    <footer className="remote-footer"><span className={error ? "offline" : "online"}></span><strong>{error ? "Link needs attention" : "Connected"}</strong><small>Updated {updated}</small></footer>
  </main>;
}
