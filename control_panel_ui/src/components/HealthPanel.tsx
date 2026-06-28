import type { PanelProps } from "./types";

const labels: Record<string, string> = {
  redbot: "Redbot",
  lavalink: "Lavalink",
  voice: "Voice",
  nuclear: "Nuclear",
  webhook: "Webhook",
};

export function HealthPanel({ state, send }: PanelProps) {
  return (
    <section className="panel">
      <h2>System Health</h2>
      <div className="health">
        {Object.entries(state.health).map(([key, item]) => (
          <div className="metric" key={key}>
            <span>{labels[key] || key}</span>
            <strong className={item.status === "online" || item.status === "configured" ? "ok" : "warn"}>
              {item.status}
            </strong>
          </div>
        ))}
      </div>
      <div className="health-actions">
        <button className="btn danger" onClick={() => void send("reset")}>Reset DjGoo</button>
        <button className="btn" onClick={() => void send("queue")}>Check Queue</button>
      </div>
    </section>
  );
}
