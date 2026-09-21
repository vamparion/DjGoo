import type { PanelProps } from "./types";
import type { DjGooProfile } from "../api";
import { setPlayerRole } from "../api";

export function GuestPanel({ state, send, profile, refresh }: PanelProps & { profile: DjGooProfile | null; refresh: () => Promise<void> }) {
  const title = state.playback.title || state.active_station?.last_track?.title || "Nothing playing";
  return (
    <section className="panel guest-panel">
      <div className="panel-title-row">
        <div>
          <h2>Players & Permissions</h2>
          <p>Requests carry a player name. Hosts can grant moderator controls.</p>
        </div>
        <button className="btn" onClick={() => void send("queue")}>Check Queue</button>
      </div>
      <div className="player-list">
        {state.gaming.profiles.map((player) => (
          <div className="row" key={player.id}>
            <div><strong>{player.username}</strong><span>{player.role}</span></div>
            <select disabled={profile?.role !== "host"} value={player.role} onChange={async (event) => { await setPlayerRole(player.id, event.target.value); await refresh(); }}>
              <option value="member">Member</option><option value="moderator">Moderator</option><option value="guest">Guest</option><option value="host">Host</option>
            </select>
          </div>
        ))}
      </div>
      <div className="guest-grid">
        <div className="phone-preview large"><div className="phone-screen"><h3>Now Playing</h3><strong>{title}</strong><button className="btn primary" onClick={() => void send("play_next", { query: title })}>Request Song</button><button className="btn" onClick={() => void send("skip")}>Vote Skip</button><button className="btn good" onClick={() => void send("more_like")}>More Like</button><button className="btn danger" onClick={() => void send("ban")}>Ban Vote</button></div></div>
        <div className="guest-copy"><h3>Shared controls</h3><p>Members vote using the configured thresholds. Moderators and the host execute controls immediately.</p><div className="mini-grid"><div className="metric"><span>Skip votes</span><strong>{state.gaming.settings.vote_thresholds.skip}</strong></div><div className="metric"><span>Ban votes</span><strong>{state.gaming.settings.vote_thresholds.ban}</strong></div><div className="metric"><span>Your role</span><strong>{profile?.role || "guest"}</strong></div><div className="metric"><span>Queue cap</span><strong>{state.gaming.settings.per_user_queue_limit}</strong></div></div></div>
      </div>
    </section>
  );
}
