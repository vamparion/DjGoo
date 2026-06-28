import type { PanelProps } from "./types";

type Props = PanelProps & {
  expanded?: boolean;
};

export function StationPanel({ state, send, expanded = false }: Props) {
  const station = state.active_station || state.stations[0] || null;
  const stations = expanded ? state.stations : state.stations.slice(0, 3);

  return (
    <section className={`panel ${expanded ? "wide-panel" : ""}`}>
      <div className="panel-title-row">
        <div>
          <h2>Radio Taste, Station-Local</h2>
          <p>Likes, dislikes, skips, and bans stay inside each station.</p>
        </div>
        <button className="btn amber" onClick={() => void send("stop_radio")}>Stop Radio</button>
      </div>
      {station ? (
        <div className="list">
          <div className="row">
            <div><strong>{station.name}</strong><span>Seed: {station.seed}</span></div>
            <button className="btn primary" onClick={() => void send("start_radio", { query: station.seed || station.name })}>Resume</button>
          </div>
          <div className="row"><div><strong>Liked: {station.liked_count}</strong><span>Only affects this station</span></div><button className="btn">Open</button></div>
          <div className="row"><div><strong>More Like: {station.more_like_count}</strong><span>Pulls station closer</span></div><button className="btn">Tune</button></div>
          <div className="row"><div><strong>Less Like: {station.less_like_count}</strong><span>Steers away locally</span></div><button className="btn">Tune</button></div>
          <div className="row"><div><strong>Banned: {station.banned_count + station.skipped_count}</strong><span>Bad picks blocked here</span></div><button className="btn">Clean</button></div>
          {expanded && stations.length > 1 && stations.map((item) => (
            <div className="row" key={item.id || item.name}>
              <div>
                <strong>{item.name}</strong>
                <span>{item.liked_count} liked, {item.less_like_count + item.banned_count} steered away</span>
              </div>
              <button className="btn" onClick={() => void send("start_radio", { query: item.seed || item.name })}>Start</button>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No station yet</strong>
          <p>Start one with a seed like 80s, Sandstorm, rock, or chill.</p>
          <button className="btn primary" onClick={() => void send("start_radio", { query: "80s" })}>Start 80s Radio</button>
        </div>
      )}
    </section>
  );
}
