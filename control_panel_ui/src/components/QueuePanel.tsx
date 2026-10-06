import { GripVertical, ListEnd, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ControlState, Track } from "../types";
import type { PanelProps } from "./types";

type Props = PanelProps & { canManage: boolean; refresh: () => Promise<ControlState | null | undefined> };

function droppedTrack(event: React.DragEvent, state: ControlState): Track | null {
  const raw = event.dataTransfer.getData("application/djgoo-track");
  if (raw) {
    try { return JSON.parse(raw) as Track; } catch { return null; }
  }
  const historyId = event.dataTransfer.getData("text/djgoo-history");
  return state.history.find((track) => track.id === historyId) || null;
}

export function QueuePanel({ state, send, canManage, refresh }: Props) {
  const [dragId, setDragId] = useState("");
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  async function reorder(draggedId: string, beforeId: string) {
    if (!draggedId || draggedId === beforeId) return;
    const ids = state.queue.map((item) => item.id || "").filter(Boolean);
    const from = ids.indexOf(draggedId);
    const to = ids.indexOf(beforeId);
    if (from < 0 || to < 0) return;
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    setDragId("");
    await send("mini_queue_reorder", { payload: { track_ids: ids } });
  }

  async function insert(event: React.DragEvent, index: number) {
    event.preventDefault();
    setDropIndex(null);
    const target = droppedTrack(event, state);
    if (!target) return;
    if (dragId) {
      if (!canManage) return;
      const before = state.queue[index]?.id || "";
      if (before) {
        await reorder(dragId, before);
      } else {
        const ids = state.queue.map((item) => item.id || "").filter((id) => id && id !== dragId);
        ids.push(dragId);
        setDragId("");
        await send("mini_queue_reorder", { payload: { track_ids: ids } });
      }
      return;
    }
    const source = target.source_uri || target.uri || "";
    if (!source.startsWith("http://") && !source.startsWith("https://")) return;
    await send("queue_insert", {
      query: source,
      payload: { index, track: { id: target.id, title: target.title, artist: target.artist, uri: source } },
    });
    await refresh();
  }

  return (
    <section className="panel queue-dock">
      <div className="panel-title-row">
        <div><h2>Queue</h2><p>{state.queue.length ? `${state.queue.length} song${state.queue.length === 1 ? "" : "s"} coming up` : "Drop a song here to line it up."}</p></div>
      </div>
      <div className="queue-sidebar-list">
        {state.queue.map((track, index) => (
          <div className={`queue-sidebar-row ${dropIndex === index ? "drop-before" : ""}`} draggable={canManage} key={track.id || `${track.uri || track.title}-${index}`}
            onDragStart={(event) => { setDragId(track.id || ""); event.dataTransfer.effectAllowed = "move"; }}
            onDragEnd={() => { setDragId(""); setDropIndex(null); }}
            onDragEnter={() => setDropIndex(index)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => void insert(event, index)}>
            {canManage && <GripVertical className="queue-grip" size={16} />}
            <div className="queue-copy"><strong>{track.title || "Untitled track"}</strong><span>{index === 0 ? "Next" : `#${index + 1}`} · {track.requester ? `Requested by ${track.requester}` : track.artist || "DjGoo"}</span></div>
            {canManage && <button className="icon-button queue-remove" title={`Remove ${track.title}`} aria-label={`Remove ${track.title}`} onClick={() => void send("remove_queue", { payload: { track_id: track.id } })}><Trash2 size={14} /></button>}
          </div>
        ))}
        <div className={`queue-end-drop ${dropIndex === state.queue.length ? "active" : ""}`}
          onDragEnter={() => setDropIndex(state.queue.length)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => void insert(event, state.queue.length)}>
          <ListEnd size={16} /><span>{state.queue.length ? "Drop at end" : "Drop into queue"}</span>
        </div>
      </div>
    </section>
  );
}
