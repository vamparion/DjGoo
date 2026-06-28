import type { PanelProps } from "./types";

export function LivePanel({ state, send }: PanelProps) {
  const playback = state.playback;
  const title = playback.title || state.active_station?.last_track?.title || "Ready for a song";
  const station = playback.station || state.active_station?.name || "No active station";
  const source = playback.source || (state.active_station?.last_track ? "Station memory" : "Idle");
  const hasTrack = title !== "Ready for a song";

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
          <button className="btn danger" onClick={() => void send("reset")}>Reset</button>
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
