import type { PanelProps } from "./types";

export function PlaylistPanel({ state, send }: PanelProps) {
  return (
    <section className="panel">
      <h2>Downtime Playlist Tools</h2>
      <div className="list">
        {state.playlists.slice(0, 6).map((playlist) => (
          <div className="row" key={playlist.name}>
            <div>
              <strong>{playlist.name}</strong>
              <span>{playlist.track_count} tracks</span>
            </div>
            <button className="btn" onClick={() => void send("play_playlist", { playlist: playlist.name })}>Play</button>
          </div>
        ))}
        {!state.playlists.length && (
          <div className="row">
            <div><strong>No saved playlists yet</strong><span>Save current tracks from Live.</span></div>
            <button className="btn" onClick={() => void send("save_current", { playlist: "chill" })}>Save</button>
          </div>
        )}
      </div>
    </section>
  );
}
