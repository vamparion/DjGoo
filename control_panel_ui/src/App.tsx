import { useEffect, useRef, useState } from "react";
import { createProfile, getState, isDirectTransportHealthy, isRemoteSession, reconnectRemote, resetDjGoo, savedProfile, sendCommand, stateRefreshIntervalMs, subscribeConnection, subscribeState } from "./api";
import { CommandBar } from "./components/CommandBar";
import { HealthPanel } from "./components/HealthPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { LivePanel } from "./components/LivePanel";
import { LogsPanel } from "./components/LogsPanel";
import { PersistentFooter } from "./components/PersistentFooter";
import { PlaylistPanel } from "./components/PlaylistPanel";
import { QueueModal } from "./components/QueueModal";
import { SearchPanel } from "./components/SearchPanel";
import { StationPanel } from "./components/StationPanel";
import { GuestPanel } from "./components/GuestPanel";
import type { ControlState } from "./types";
import type { DjGooProfile } from "./api";
import { Onboarding } from "./components/Onboarding";
import { GamingSettings } from "./components/GamingSettings";
import { optimisticallyTogglePlayback } from "./playbackClock";

const views = ["Live", "Find", "History", "Radio", "Lists", "Players", "Settings", "Logs"] as const;
type View = (typeof views)[number];

export function App() {
  const compact = new URLSearchParams(window.location.search).get("view") === "compact";
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Ready");
  const [activeView, setActiveView] = useState<View>("Live");
  const [profile, setProfile] = useState<DjGooProfile | null>(() => savedProfile());
  const [queueOpen, setQueueOpen] = useState(false);
  const refreshStarted = useRef(0);
  const refreshApplied = useRef(0);
  const role = isRemoteSession() ? (state?.session?.role || profile?.role || "guest") : "host";
  const canManage = role === "host" || role === "moderator";
  const visibleViews = views.filter((view) => canManage || !["Players", "Settings", "Logs"].includes(view));

  async function refresh() {
    const requestNumber = ++refreshStarted.current;
    try {
      const next = await getState();
      if (requestNumber < refreshApplied.current) return next;
      refreshApplied.current = requestNumber;
      setState(next);
      if (next.session) setProfile({ id: next.session.discord_user_id || "remote", token: "", username: next.session.display_name, role: next.session.role });
      setError("");
    } catch (err) {
      setError(String((err as Error).message || err));
      return null;
    }
  }

  useEffect(() => {
    let timer = 0;
    let stopped = false;
    const poll = async () => {
      window.clearTimeout(timer);
      if (stopped || document.hidden) return;
      await refresh();
      if (!stopped && !document.hidden) {
        timer = window.setTimeout(poll, stateRefreshIntervalMs());
      }
    };
    const visibilityChanged = () => {
      window.clearTimeout(timer);
      if (!document.hidden) {
        reconnectRemote();
        void poll();
      }
    };
    const unsubscribeState = subscribeState(next => {
      refreshApplied.current = ++refreshStarted.current;
      setState(next);
      if (next.session) setProfile({ id: next.session.discord_user_id || "remote", token: "", username: next.session.display_name, role: next.session.role });
      setError("");
    });
    const unsubscribeConnection = subscribeConnection(() => {
      window.clearTimeout(timer);
      if (!stopped && !document.hidden) timer = window.setTimeout(poll, stateRefreshIntervalMs());
    });
    document.addEventListener("visibilitychange", visibilityChanged);
    void poll();
    return () => { stopped = true; window.clearTimeout(timer); unsubscribeState(); unsubscribeConnection(); document.removeEventListener("visibilitychange", visibilityChanged); };
  }, []);

  async function send(action: string, payload: Record<string, unknown> = {}) {
    if (action === "queue") {
      setQueueOpen(true);
      await refresh();
      return;
    }
    setStatus(`Sending ${action}`);
    if (action === "toggle_pause") {
      setState(current => current ? optimisticallyTogglePlayback(current) : current);
    }
    try {
      if (action === "reset") {
        await resetDjGoo();
      } else {
        await sendCommand(action, payload);
      }
      setStatus(`Sent ${action}`);
      if (action === "toggle_pause") {
        window.setTimeout(() => void refresh(), 750);
        window.setTimeout(() => void refresh(), 2500);
      } else {
        await refresh();
      }
      if (!isDirectTransportHealthy() && ["play_next", "play_now", "play", "skip", "stop", "start_radio", "radio"].includes(action)) {
        window.setTimeout(() => void refresh(), 2000);
        window.setTimeout(() => void refresh(), 6000);
      }
    } catch (err) {
      setError(String((err as Error).message || err));
      setStatus("Error");
      if (action === "toggle_pause") void refresh();
    }
  }

  if (!state) {
    return (
      <main className="loading loading-state">
        <img className="loading-mark" src="./icons/djgoo-192.png" alt="" />
        <strong>{error ? "DjGoo could not load" : "Loading DjGoo..."}</strong>
        {error && <><p>{error}</p><div className="inline-actions"><button className="btn primary" onClick={() => void refresh()}>Reconnect</button></div><p className="muted">Your paired device remains saved. Reconnecting does not require another Discord command.</p></>}
      </main>
    );
  }

  function renderView() {
    if (activeView === "Find") {
      return <SearchPanel state={state} send={send} />;
    }
    if (activeView === "History") {
      return <HistoryPanel state={state} send={send} canManage={canManage} refresh={refresh} />;
    }
    if (activeView === "Radio") {
      return (
        <>
          <StationPanel state={state} send={send} expanded canManage={canManage} />
        </>
      );
    }
    if (activeView === "Lists") {
      return <PlaylistPanel state={state} send={send} expanded canManage={canManage} />;
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
        <LivePanel state={state} send={send} openFind={() => setActiveView("Find")} />
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
          {compact ? <LivePanel state={state} send={send} openFind={() => setActiveView("Find")} /> : renderView()}
        </section>
        {!compact && <aside className="side">
          <HealthPanel state={state} send={send} />
          <PlaylistPanel state={state} send={send} compact canManage={canManage} refresh={refresh} />
          {canManage && <LogsPanel state={state} send={send} />}
        </aside>}
      </main>
      <PersistentFooter state={state} send={send} status={status} />
      {queueOpen && <QueueModal state={state} send={send} close={() => setQueueOpen(false)} />}
    </div>
  );
}
