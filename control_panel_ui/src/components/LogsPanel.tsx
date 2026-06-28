import type { PanelProps } from "./types";

function flattenLogs(logs: PanelProps["state"]["logs"]) {
  return Object.entries(logs)
    .flatMap(([source, lines]) => lines.slice(-8).map((line) => ({ source, line })))
    .slice(-14)
    .reverse();
}

export function LogsPanel({ state, expanded = false }: PanelProps & { expanded?: boolean }) {
  const lines = flattenLogs(state.logs);
  return (
    <section className={`panel ${expanded ? "wide-panel" : ""}`}>
      <div className="panel-title-row">
        <div>
          <h2>{expanded ? "Activity And Diagnostics" : "Recent Activity"}</h2>
          <p>{expanded ? "Useful when playback feels wrong or a service is offline." : "Last useful signals from DjGoo."}</p>
        </div>
      </div>
      <div className="log-list">
        {lines.length ? (
          lines.map((entry, index) => (
            <div className="log-line" key={`${entry.source}-${index}`}>
              <span>{entry.source}</span>
              <code>{entry.line}</code>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>No recent logs available</strong>
            <p>DjGoo will show Redbot and voice listener activity here once logs are written.</p>
          </div>
        )}
      </div>
    </section>
  );
}
