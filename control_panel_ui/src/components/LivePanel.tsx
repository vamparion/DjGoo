import { useEffect, useState } from "react";
import { ListMusic, Pause, Play, Search, SkipForward, Square, Volume1, Volume2 } from "lucide-react";
import type { PanelProps } from "./types";
import { playbackPosition } from "../playbackClock";

function clock(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

type Props = PanelProps & { openFind?: () => void };

export function LivePanel({ state, send, openFind }: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!state.playback.playing) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.playback.playing, state.playback.title, state.playback.measured_at]);
  const playback = state.playback;
  const title = playback.title || state.active_station?.last_track?.title || "Ready for a song";
  const station = playback.station || state.active_station?.name || "No active station";
  const source = playback.source || (state.active_station?.last_track ? "Station memory" : "Idle");
  const hasTrack = title !== "Ready for a song";
  const radioActive = Boolean(playback.station || state.active_station?.name);
  const elapsed = playbackPosition(playback, now);
  const duration = Number(playback.duration_ms || 0);

  return (
    <section className="panel hero">
      <div className={`art ${playback.playing ? "playing" : ""}`}>
        <img src={playback.artwork_url || "./icons/djgoo-192.png"} alt="" />
        <span>{hasTrack ? "ON" : "IDLE"}</span>
      </div>
      <div>
        <h1 className="title">{title}</h1>
        <div className="meta">
          <span>{station}</span>
          <span>{source}</span>
          <span>{playback.remaining || "time unknown"}</span>
          <span>Queue: {playback.queue_count}</span>
        </div>
        {duration > 0 && <div className="playback-progress"><progress max={duration} value={Math.min(elapsed, duration)} /><span>{clock(elapsed)} / {clock(duration)}</span></div>}
        {!hasTrack ? <div className="live-empty-actions">
          <button className="btn primary icon-action" onClick={openFind}><Search size={16} /><span>Find music</span></button>
          <button className="btn icon-action" onClick={() => void send("queue")}><ListMusic size={16} /><span>View queue</span></button>
        </div> : <>
          <div className="transport-actions" aria-label="Playback controls">
            <button className="btn primary icon-action" onClick={() => void send("toggle_pause")}>
              {playback.playing ? <Pause size={16} /> : <Play size={16} />}
              <span>{playback.playing ? "Pause" : "Resume"}</span>
            </button>
            <button className="btn primary icon-action" onClick={() => void send("skip")}><SkipForward size={16} /><span>Skip</span></button>
            <button className="btn danger icon-action" title="Stop playback and clear the queue" onClick={() => void send("stop")}><Square size={15} /><span>Stop</span></button>
            <button className="btn icon-action" onClick={() => void send("queue")}><ListMusic size={16} /><span>Queue</span></button>
            <button className="icon-button" title="Volume down" aria-label="Volume down" onClick={() => void send("volume_down")}><Volume1 size={18} /></button>
            <button className="icon-button" title="Volume up" aria-label="Volume up" onClick={() => void send("volume_up")}><Volume2 size={18} /></button>
          </div>
          <div className="track-actions">
            <button className="btn" onClick={() => void send("save_current", { playlist: "favorites" })}>Save to favorites</button>
            {radioActive && <>
              <button className="btn good" onClick={() => void send("like")}>Like</button>
              <button className="btn" onClick={() => void send("more_like")}>More like this</button>
              <button className="btn" onClick={() => void send("less_like")}>Less like this</button>
              <button className="btn danger" onClick={() => void send("ban")}>Ban from station</button>
              <button className="btn amber" onClick={() => void send("stop_radio")}>Stop radio</button>
            </>}
          </div>
        </>}
      </div>
    </section>
  );
}
