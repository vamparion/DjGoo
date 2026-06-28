import type { PanelProps } from "./types";

export function QueuePanel({ state, send }: PanelProps) {
  const queue = state.queue.length ? state.queue : [
    { title: "Queue details appear here when DjGoo can read Redbot live state." },
  ];

  return (
    <section className="panel">
      <h2>Queue, One-Tap Editable</h2>
      <div className="list">
        {queue.slice(0, 5).map((track, index) => (
          <div className="row" key={`${track.uri || track.title}-${index}`}>
            <div>
              <strong>{track.title || "Untitled track"}</strong>
              <span>{index === 0 ? "Next visible item" : "Queued"}</span>
            </div>
            <button className="btn" onClick={() => void send("queue")}>Queue</button>
          </div>
        ))}
      </div>
    </section>
  );
}
