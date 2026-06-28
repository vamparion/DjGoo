import type { PanelProps } from "./types";

export function GuestPanel({ state, send }: PanelProps) {
  const title = state.playback.title || state.active_station?.last_track?.title || "Nothing playing";
  return (
    <section className="panel guest-panel">
      <div className="panel-title-row">
        <div>
          <h2>Guest Control Preview</h2>
          <p>Phone-first controls for friends once remote access is enabled.</p>
        </div>
        <button className="btn" onClick={() => void send("queue")}>Check Queue</button>
      </div>
      <div className="guest-grid">
        <div className="phone-preview large">
          <div className="phone-screen">
            <h3>Now Playing</h3>
            <strong>{title}</strong>
            <button className="btn primary" disabled>Request Song</button>
            <button className="btn" disabled>Vote Skip</button>
            <button className="btn good" disabled>Like</button>
            <button className="btn danger" disabled>Report Bad Pick</button>
          </div>
        </div>
        <div className="guest-copy">
          <h3>Built for no keyboard</h3>
          <p>Guests should be able to request, vote, like, and see what is playing from a phone without touching your Rocket League setup.</p>
          <div className="mini-grid">
            <div className="metric"><span>Status</span><strong>Local admin first</strong></div>
            <div className="metric"><span>Access</span><strong>Private LAN later</strong></div>
            <div className="metric"><span>Safety</span><strong>Approval controls</strong></div>
            <div className="metric"><span>Priority</span><strong>Now playing first</strong></div>
          </div>
        </div>
      </div>
    </section>
  );
}
