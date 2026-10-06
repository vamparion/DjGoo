import type { PanelProps } from "./types";
import type { DjGooProfile } from "../api";
import { isRemoteSession, revokePlayer, setPairedPlayerRole } from "../api";

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
        {(state.players || []).map((player) => (
          <div className="row player-row" key={player.id}>
            <div><strong>{player.username}</strong><span>{player.online ? "Online now" : `Last active ${new Date(player.last_seen * 1000).toLocaleString()}`}</span><span>{player.device_name} · {player.device_type} · {player.device_count || 1} device{(player.device_count || 1) === 1 ? "" : "s"}</span><span className="player-id">Discord ID {player.discord_user_id}</span></div>
            <div className="player-controls"><span className={`status-pill ${player.online ? "online" : ""}`}>{player.online ? "online" : "offline"}</span>{!isRemoteSession() ? <><label>Access<select value={player.role} onChange={async (event) => { await setPairedPlayerRole(player.discord_user_id, event.target.value, state.session?.guild_id); await refresh(); }}><option value="member">Member</option><option value="moderator">Moderator</option><option value="host">Host</option></select></label><button className="btn danger" onClick={async () => { await revokePlayer(player.discord_user_id, state.session?.guild_id); await refresh(); }}>Revoke devices</button></> : <span className="role-badge">{player.role}</span>}</div>
          </div>
        ))}
        {!(state.players || []).length && <div className="empty-state"><strong>No paired players yet</strong><p>Players appear here after opening their private DjGoo link.</p></div>}
      </div>
      <div className="guest-grid">
        <div className="phone-preview large"><div className="phone-screen"><h3>Now Playing</h3><strong>{title}</strong><button className="btn primary" onClick={() => void send("play_next", { query: title })}>Request Song</button><button className="btn" onClick={() => void send("skip")}>Vote Skip</button><button className="btn good" onClick={() => void send("more_like")}>More Like</button><button className="btn danger" onClick={() => void send("ban")}>Ban Vote</button></div></div>
        <div className="guest-copy"><h3>Shared controls</h3><p>Members vote using the configured thresholds. Moderators and the host execute controls immediately.</p><div className="mini-grid"><div className="metric"><span>Skip votes</span><strong>{state.gaming.settings.vote_thresholds.skip}</strong></div><div className="metric"><span>Ban votes</span><strong>{state.gaming.settings.vote_thresholds.ban}</strong></div><div className="metric"><span>Your role</span><strong>{profile?.role || "guest"}</strong></div><div className="metric"><span>Queue cap</span><strong>{state.gaming.settings.per_user_queue_limit}</strong></div></div></div>
      </div>
    </section>
  );
}
