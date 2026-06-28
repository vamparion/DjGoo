import type { PanelProps } from "./types";

export function QueuePanel({ state, send }: PanelProps) {
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
                <span>{index === 0 ? "Next up" : `#${index + 1} queued`}</span>
              </div>
              <button className="btn" onClick={() => void send("skip")}>Skip To</button>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No readable queue yet</strong>
          <p>DjGoo can still send queue, skip, stop, and play commands. Live queue reading will fill this list when Redbot exposes it.</p>
          <div className="inline-actions">
            <button className="btn" onClick={() => void send("queue")}>Ask Redbot</button>
            <button className="btn primary" onClick={() => void send("play_next", { query: "sandstorm" })}>Test Song</button>
          </div>
        </div>
      )}
    </section>
  );
}
