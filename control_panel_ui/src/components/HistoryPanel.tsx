import { Clock3, GripVertical, ListPlus, Play, Trash2 } from "lucide-react";
import { playlistAction } from "../api";
import type { PanelProps } from "./types";

type Props = PanelProps & { canManage: boolean; refresh: () => Promise<unknown> };

function playedAt(value: number) {
  if (!value) return "Recently played";
  return new Date(value * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
}

export function HistoryPanel({ state, send, canManage, refresh }: Props) {
  async function add(trackId: string, playlist: string) {
    if (!trackId || !playlist) return;
    await playlistAction("history-add", { playlist, track_id: trackId });
    await refresh();
  }

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
      {canManage && state.playlists.length > 0 && (
        <div className="history-drop-grid sticky-drop-targets" aria-label="Playlist drop targets">
          {state.playlists.map((playlist) => (
            <button
              className="history-drop-target"
              key={playlist.name}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => void add(event.dataTransfer.getData("text/djgoo-history"), playlist.name)}
            >
              <ListPlus size={16} />
              <span>Drop into <strong>{playlist.name}</strong></span>
            </button>
          ))}
        </div>
      )}
      <div className="history-list">
        {state.history.map((track) => (
          <article
            className="history-row"
            draggable={canManage}
            key={`${track.id}-${track.played_at}`}
            onDragStart={(event) => event.dataTransfer.setData("text/djgoo-history", track.id || "")}
          >
            <GripVertical className={canManage ? "history-grip" : "history-grip disabled"} size={18} />
            <div className="history-copy">
              <strong>{track.title}</strong>
              <span>{track.artist || track.mode || "DjGoo"} · {playedAt(track.played_at)}</span>
            </div>
            <button className="btn icon-action" onClick={() => void send("play_next", { query: track.uri || `${track.title} ${track.artist || ""}` })}>
              <Play size={15} /><span>Play next</span>
            </button>
            {canManage && <button className="icon-button history-remove" title="Remove from history" aria-label={`Remove ${track.title} from history`} onClick={() => void remove(track.id || "")}><Trash2 size={15} /></button>}
          </article>
        ))}
        {state.history.length === 0 && <div className="empty-state"><strong>No recent songs yet</strong><p>Played tracks will appear here automatically.</p></div>}
      </div>
    </section>
  );
}
