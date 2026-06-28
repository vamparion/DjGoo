import { useEffect, useState } from "react";
import { getState, resetDjGoo, sendCommand } from "./api";
import { CommandBar } from "./components/CommandBar";
import { HealthPanel } from "./components/HealthPanel";
import { LivePanel } from "./components/LivePanel";
import { PersistentFooter } from "./components/PersistentFooter";
import { PlaylistPanel } from "./components/PlaylistPanel";
import { QueuePanel } from "./components/QueuePanel";
import { SmartActions } from "./components/SmartActions";
import { StationPanel } from "./components/StationPanel";
import type { ControlState } from "./types";

export function App() {
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Ready");

  async function refresh() {
    try {
      setState(await getState());
      setError("");
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, []);

  async function send(action: string, payload: Record<string, unknown> = {}) {
    setStatus(`Sending ${action}`);
    try {
      if (action === "reset") {
        await resetDjGoo();
      } else {
        await sendCommand(action, payload);
      }
      setStatus(`Sent ${action}`);
      await refresh();
    } catch (err) {
      setError(String((err as Error).message || err));
      setStatus("Error");
    }
  }

  if (!state) {
    return <main className="loading">Loading DjGoo...</main>;
  }

  return (
    <div className="app">
      <CommandBar send={send} />
      {error && <div className="banner error">{error}</div>}
      <main className="content">
        <nav className="rail" aria-label="DjGoo tools">
          <button className="active">Live</button>
          <button>Find</button>
          <button>Radio</button>
          <button>Lists</button>
          <button>Guests</button>
          <button>Logs</button>
        </nav>
        <section className="stack">
          <LivePanel state={state} send={send} />
          <SmartActions state={state} send={send} />
          <div className="split">
            <QueuePanel state={state} send={send} />
            <StationPanel state={state} send={send} />
          </div>
        </section>
        <aside className="side">
          <HealthPanel state={state} send={send} />
          <PlaylistPanel state={state} send={send} />
          <section className="panel">
            <h2>Guest Mode Later</h2>
            <div className="phone-preview">
              <div className="phone-screen">
                <h3>DjGoo Remote</h3>
                <p>Now playing visible first.</p>
                <button className="btn primary" disabled>Request Song</button>
                <button className="btn" disabled>Vote Skip</button>
                <button className="btn good" disabled>Like</button>
                <button className="btn" disabled>Queue</button>
              </div>
            </div>
          </section>
        </aside>
      </main>
      <PersistentFooter state={state} send={send} status={status} />
    </div>
  );
}
