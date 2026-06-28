import type { PanelProps } from "./types";

export function StationPanel({ state, send }: PanelProps) {
  const station = state.active_station || state.stations[0] || null;

  return (
    <section className="panel">
      <h2>Radio Taste, Station-Local</h2>
      {station ? (
        <div className="list">
          <div className="row">
            <div><strong>{station.name}</strong><span>Seed: {station.seed}</span></div>
            <button className="btn amber" onClick={() => void send("stop_radio")}>Stop</button>
          </div>
          <div className="row"><div><strong>Liked: {station.liked_count}</strong><span>Only affects this station</span></div><button className="btn">Open</button></div>
          <div className="row"><div><strong>More Like: {station.more_like_count}</strong><span>Pulls station closer</span></div><button className="btn">Tune</button></div>
          <div className="row"><div><strong>Less Like: {station.less_like_count}</strong><span>Steers away locally</span></div><button className="btn">Tune</button></div>
          <div className="row"><div><strong>Banned: {station.banned_count + station.skipped_count}</strong><span>Bad picks blocked here</span></div><button className="btn">Clean</button></div>
        </div>
      ) : (
        <p>No station yet. Start one from the command bar.</p>
      )}
    </section>
  );
}
