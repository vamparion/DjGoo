import type { PanelProps } from "./types";
import { downloadBackup } from "../api";

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
        </div>{expanded && <button className="btn" onClick={() => void downloadBackup()}>Export DjGoo Backup</button>}
      </div>
      {expanded && <div className="timeline">{state.timeline.map((item, index) => <div className="timeline-item" key={`${item.time}-${index}`}><span>{item.time ? new Date(item.time).toLocaleTimeString() : "Now"}</span><div><strong>{item.title}</strong><p>{item.detail}</p></div></div>)}</div>}
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
            <p>DjGoo will show Music Core and voice-control activity here once logs are written.</p>
          </div>
        )}
      </div>
    </section>
  );
}
