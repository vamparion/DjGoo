import type { PanelProps } from "./types";
import { savedProfile } from "../api";

export function QueuePanel({ state, send }: PanelProps) {
  const role = savedProfile()?.role || "guest";
  const canModerate = role === "host" || role === "moderator";
  return (
    <section className="panel">
      <div className="panel-title-row">
        <div>
          <h2>Queue Control</h2>
          <p>Fast checks and recovery when playback feels stuck.</p>
        </div>
        <button className="btn" onClick={() => void send("queue")}>Refresh</button>
      </div>
      {state.queue.length ? (
        <div className="list">
          {state.queue.slice(0, 5).map((track, index) => (
            <div className="row" key={`${track.uri || track.title}-${index}`}>
              <div>
                <strong>{track.title || "Untitled track"}</strong>
                <span>
                  {index === 0 ? "Next up" : `#${index + 1} queued`}
                  {track.requester ? ` · Requested by ${track.requester}` : " · DjGoo selection"}
                </span>
              </div>
              {canModerate ? (
                <button className="btn danger" onClick={() => void send("remove_queue", { payload: { track_id: track.id } })}>Remove</button>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No readable queue yet</strong>
          <p>Requests and radio additions will appear here as soon as DjGoo confirms them.</p>
          <div className="inline-actions">
            <button className="btn" onClick={() => void send("queue")}>Refresh</button>
            <button className="btn primary" onClick={() => void send("play_next", { query: "sandstorm" })}>Test Song</button>
          </div>
        </div>
      )}
    </section>
  );
}
