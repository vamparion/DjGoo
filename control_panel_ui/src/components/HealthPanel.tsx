import type { PanelProps } from "./types";

const labels: Record<string, string> = {
  redbot: "Music Core",
  lavalink: "Lavalink",
  voice: "Voice",
  nuclear: "Nuclear",
  webhook: "Webhook",
};

export function HealthPanel({ state, send }: PanelProps) {
  const unhealthy = Object.entries(state.health).filter(([, item]) => !["online", "configured"].includes(item.status));
  return (
    <section className="panel health-panel">
      <div className="health-title"><h2>DjGoo</h2><span>{unhealthy.length ? "Needs attention" : "Running"}</span></div>
      <div className="health" aria-label="Component health">
        {Object.entries(state.health).map(([key, item]) => (
          <span className="health-led" key={key} title={`${labels[key] || key}: ${item.status}${item.detail ? ` - ${item.detail}` : ""}`}><i className={["online", "configured"].includes(item.status) ? "dot ok-bg" : "dot warn-bg"} />{labels[key] || key}</span>
        ))}
      </div>
      {unhealthy.length > 0 && <div className="health-problems">{unhealthy.map(([key, item]) => <p key={key}><strong>{labels[key] || key}</strong>: {item.detail || item.status}</p>)}{state.capabilities?.system_management !== false && <button className="btn danger" onClick={() => void send("reset")}>Repair now</button>}</div>}
    </section>
  );
}
