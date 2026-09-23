import { useEffect, useState } from "react";
import type { PanelProps } from "./types";

function clock(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function LivePanel({ state, send }: PanelProps) {
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
  const canRecover = state.capabilities?.system_management !== false;
  const anchored = Number(playback.position_ms || 0);
  const elapsed = playback.playing && playback.measured_at
    ? anchored + Math.max(0, now - playback.measured_at * 1000)
    : anchored;
  const duration = Number(playback.duration_ms || 0);

  return (
    <section className="panel hero">
      <div className={`art ${hasTrack ? "playing" : ""}`}>
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
        <div className="actions">
          <button className="btn primary" onClick={() => void send("toggle_pause")}>Pause/Resume</button>
          <button className="btn primary" onClick={() => void send("skip")}>Skip</button>
          <button className="btn good" onClick={() => void send("like")}>Like</button>
          <button className="btn" onClick={() => void send("more_like")}>More Like</button>
          <button className="btn" onClick={() => void send("less_like")}>Less Like</button>
          <button className="btn danger" onClick={() => void send("ban")}>Ban</button>
          <button className="btn amber" onClick={() => void send("stop_radio")}>Stop Radio</button>
          <button className="btn" onClick={() => void send("save_current", { playlist: "favorites" })}>Save</button>
          <button className="btn" onClick={() => void send("queue")}>Queue</button>
          <button className="btn" onClick={() => void send("volume_down")}>Vol -</button>
          <button className="btn" onClick={() => void send("volume_up")}>Vol +</button>
          {canRecover && <button className="btn danger" onClick={() => void send("reset")}>Reset</button>}
        </div>
        <div className="hint-strip">
          <button onClick={() => void send("play_next", { query: "sandstorm" })}>Play Sandstorm</button>
          <button onClick={() => void send("start_radio", { query: "80s" })}>Start 80s radio</button>
          <button onClick={() => void send("save_current", { playlist: "favorites" })}>Save to favorites</button>
        </div>
      </div>
    </section>
  );
}
