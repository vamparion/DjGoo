import { useEffect, useState } from "react";
import { createProfile, getState, isRemoteSession, resetDjGoo, savedProfile, sendCommand } from "./api";
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
import type { DjGooProfile } from "./api";
import { Onboarding } from "./components/Onboarding";
import { GamingSettings } from "./components/GamingSettings";

const views = ["Live", "Find", "Radio", "Lists", "Players", "Settings", "Logs"] as const;
type View = (typeof views)[number];

export function App() {
  const compact = new URLSearchParams(window.location.search).get("view") === "compact";
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Ready");
  const [activeView, setActiveView] = useState<View>("Live");
  const [profile, setProfile] = useState<DjGooProfile | null>(() => savedProfile());
  const role = state?.session?.role || profile?.role || "guest";
  const canManage = role === "host" || role === "moderator";
  const visibleViews = views.filter((view) => canManage || !["Players", "Settings", "Logs"].includes(view));

  async function refresh() {
    try {
      const next = await getState();
      setState(next);
      if (next.session) setProfile({ id: next.session.discord_user_id || "remote", token: "", username: next.session.display_name, role: next.session.role });
      setError("");
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  }

  useEffect(() => {
    void refresh();
    let timer = 0;
    const schedule = () => {
      window.clearInterval(timer);
      if (!document.hidden) timer = window.setInterval(refresh, isRemoteSession() ? 15000 : 3000);
    };
    document.addEventListener("visibilitychange", schedule);
    schedule();
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", schedule); };
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
    if (activeView === "Players") {
      return <GuestPanel state={state} send={send} profile={profile} refresh={refresh} />;
    }
    if (activeView === "Settings") {
      return <GamingSettings state={state} refresh={refresh} host={profile?.role === "host"} />;
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

  if (!profile && !isRemoteSession()) {
    return <Onboarding submit={async (username) => setProfile(await createProfile(username))} />;
  }

  return (
    <div className={`app ${state.gaming.settings.ranked_mode ? "ranked-mode" : ""} ${isRemoteSession() ? "remote-mode" : ""} ${compact ? "compact-mode" : ""}`}>
      <CommandBar send={send} />
      {error && <div className="banner error">{error}</div>}
      <main className="content">
        {!compact && <nav className="rail" aria-label="DjGoo tools">
          {visibleViews.map((view) => (
            <button
              className={activeView === view ? "active" : ""}
              key={view}
              onClick={() => setActiveView(view)}
              type="button"
            >
              {view}
            </button>
          ))}
        </nav>}
        <section className="stack">
          {compact ? <><LivePanel state={state} send={send} /><QueuePanel state={state} send={send} /></> : renderView()}
        </section>
        {!compact && <aside className="side">
          <HealthPanel state={state} send={send} />
          <PlaylistPanel state={state} send={send} compact />
          {canManage && <LogsPanel state={state} send={send} />}
        </aside>}
      </main>
      <PersistentFooter state={state} send={send} status={status} />
    </div>
  );
}
