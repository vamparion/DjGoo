import { useState } from "react";
import type { PanelProps } from "./types";
import { savedProfile } from "../api";

export function QueuePanel({ state, send }: PanelProps) {
  const [dragId, setDragId] = useState("");
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
          {state.queue.map((track, index) => (
            <div className="row" draggable={canModerate} key={track.id || `${track.uri || track.title}-${index}`}
              onDragStart={() => setDragId(track.id || "")}
              onDragOver={(event) => { if (canModerate) event.preventDefault(); }}
              onDrop={() => { const before = track.id || ""; if (!dragId || dragId === before) return; const ids = state.queue.map(item => item.id || "").filter(Boolean); const from = ids.indexOf(dragId); const to = ids.indexOf(before); if (from < 0 || to < 0) return; ids.splice(to, 0, ids.splice(from, 1)[0]); setDragId(""); void send("mini_queue_reorder", { payload: { track_ids: ids } }); }}>
              {canModerate && <div className="drag-handle" title="Drag to reorder">⋮⋮</div>}
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
