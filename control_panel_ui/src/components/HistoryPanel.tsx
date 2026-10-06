import { Clock3, GripVertical, Play, Trash2 } from "lucide-react";
import { playlistAction } from "../api";
import type { PanelProps } from "./types";

type Props = PanelProps & { canManage: boolean; refresh: () => Promise<unknown> };

function playedAt(value: number) {
  if (!value) return "Recently played";
  return new Date(value * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
}

export function HistoryPanel({ state, send, canManage, refresh }: Props) {
  async function remove(trackId: string) {
    if (!trackId) return;
    await playlistAction("history-delete", { track_id: trackId });
    await refresh();
  }

  return (
    <section className="panel history-panel">
      <div className="panel-title-row">
        <div><h2>Recently Played</h2><p>Return to a song or organize recent music into a playlist.</p></div>
        <Clock3 size={20} />
      </div>
      <div className="history-list">
        {state.history.map((track) => {
          const source = track.source_uri || track.uri || "";
          const playable = source.startsWith("https://") || source.startsWith("http://");
          return (
          <article
            className="history-row"
            draggable={canManage && playable}
            key={`${track.id}-${track.played_at}`}
            onDragStart={(event) => event.dataTransfer.setData("text/djgoo-history", track.id || "")}
          >
            <GripVertical className={canManage ? "history-grip" : "history-grip disabled"} size={18} />
            <div className="history-copy">
              <strong>{track.title}</strong>
              <span>{track.artist || track.mode || "DjGoo"} · {playedAt(track.played_at)}</span>
            </div>
            <button className="btn icon-action" disabled={!playable} title={playable ? "Play this exact source next" : "Original source unavailable"} onClick={() => void send("play_next", { query: source })}>
              <Play size={15} /><span>Play next</span>
            </button>
            {canManage && <button className="icon-button history-remove" title="Remove from history" aria-label={`Remove ${track.title} from history`} onClick={() => void remove(track.id || "")}><Trash2 size={15} /></button>}
          </article>
          );
        })}
        {state.history.length === 0 && <div className="empty-state"><strong>No recent songs yet</strong><p>Played tracks will appear here automatically.</p></div>}
      </div>
    </section>
  );
}
