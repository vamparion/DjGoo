import { useEffect, useState } from "react";
import { getState, resetDjGoo, sendCommand } from "./api";
import { CommandBar } from "./components/CommandBar";
import { HealthPanel } from "./components/HealthPanel";
import { LivePanel } from "./components/LivePanel";
import { LogsPanel } from "./components/LogsPanel";
import { PersistentFooter } from "./components/PersistentFooter";
import { PlaylistPanel } from "./components/PlaylistPanel";
import { QueuePanel } from "./components/QueuePanel";
import { SearchPanel } from "./components/SearchPanel";
import { SmartActions } from "./components/SmartActions";
import { StationPanel } from "./components/StationPanel";
import { GuestPanel } from "./components/GuestPanel";
import type { ControlState } from "./types";

const views = ["Live", "Find", "Radio", "Lists", "Guests", "Logs"] as const;
type View = (typeof views)[number];

export function App() {
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Ready");
  const [activeView, setActiveView] = useState<View>("Live");

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

  function renderView() {
    if (activeView === "Find") {
      return <SearchPanel state={state} send={send} />;
    }
    if (activeView === "Radio") {
      return (
        <>
          <StationPanel state={state} send={send} expanded />
          <SmartActions state={state} send={send} mode="radio" />
        </>
      );
    }
    if (activeView === "Lists") {
      return <PlaylistPanel state={state} send={send} expanded />;
    }
    if (activeView === "Guests") {
      return <GuestPanel state={state} send={send} />;
    }
    if (activeView === "Logs") {
      return <LogsPanel state={state} send={send} expanded />;
    }
    return (
      <>
        <LivePanel state={state} send={send} />
        <SmartActions state={state} send={send} />
        <div className="split">
          <QueuePanel state={state} send={send} />
          <StationPanel state={state} send={send} />
        </div>
      </>
    );
  }

  return (
    <div className="app">
      <CommandBar send={send} />
      {error && <div className="banner error">{error}</div>}
      <main className="content">
        <nav className="rail" aria-label="DjGoo tools">
          {views.map((view) => (
            <button
              className={activeView === view ? "active" : ""}
              key={view}
              onClick={() => setActiveView(view)}
              type="button"
            >
              {view}
            </button>
          ))}
        </nav>
        <section className="stack">
          {renderView()}
        </section>
        <aside className="side">
          <HealthPanel state={state} send={send} />
          <PlaylistPanel state={state} send={send} compact />
          <LogsPanel state={state} send={send} />
        </aside>
      </main>
      <PersistentFooter state={state} send={send} status={status} />
    </div>
  );
}
