import type { PanelProps } from "./types";

export function LivePanel({ state, send }: PanelProps) {
  const playback = state.playback;
  const title = playback.title || state.active_station?.last_track?.title || "Nothing playing yet";
  const station = playback.station || state.active_station?.name || "No active station";
  const source = playback.source || "DjGoo state";

  return (
    <section className="panel hero">
      <div className="art" />
      <div>
        <h1 className="title">{title}</h1>
        <div className="meta">
          {station} | {source} | {playback.remaining || "time unknown"} | Queue: {playback.queue_count}
        </div>
        <div className="actions">
          <button className="btn primary" onClick={() => void send("toggle_pause")}>Pause</button>
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
      </div>
    </section>
  );
}
