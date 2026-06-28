import type { PanelProps } from "./types";

type Props = PanelProps & {
  compact?: boolean;
  expanded?: boolean;
};

export function PlaylistPanel({ state, send, compact = false, expanded = false }: Props) {
  const visiblePlaylists = state.playlists.slice(0, compact ? 4 : 12);
  return (
    <section className={`panel ${expanded ? "wide-panel" : ""}`}>
      <div className="panel-title-row">
        <div>
          <h2>{compact ? "Playlists" : "Playlist Workshop"}</h2>
          <p>{expanded ? "Save the current song, launch a list, or use simple names that match how you talk." : "Fast access to saved lists."}</p>
        </div>
        {!compact && <button className="btn" onClick={() => void send("save_current", { playlist: "favorites" })}>Save Current</button>}
      </div>
      {!compact && (
        <div className="chip-row">
          {["favorites", "chill", "80s", "edm", "white girl music", "rock"].map((playlist) => (
            <button className="chip" key={playlist} onClick={() => void send("save_current", { playlist })}>
              Add to {playlist}
            </button>
          ))}
        </div>
      )}
      <div className="list">
        {visiblePlaylists.map((playlist) => (
          <div className="row" key={playlist.name}>
            <div>
              <strong>{playlist.name}</strong>
              <span>{playlist.track_count} tracks</span>
            </div>
            <button className="btn" onClick={() => void send("play_playlist", { playlist: playlist.name })}>Play</button>
          </div>
        ))}
        {!state.playlists.length && (
          <div className="empty-state">
            <strong>No saved playlists yet</strong>
            <p>Use Save on the live player or one of the playlist chips to start building lists.</p>
            <button className="btn" onClick={() => void send("save_current", { playlist: "chill" })}>Save</button>
          </div>
        )}
      </div>
    </section>
  );
}
