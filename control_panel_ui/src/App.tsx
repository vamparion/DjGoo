import { useEffect, useRef, useState } from "react";
import { House, ListMusic, Menu, Search, X } from "lucide-react";
import { createProfile, getState, isDirectTransportHealthy, isRemoteSession, reconnectRemote, resetDjGoo, savedProfile, sendCommand, stateRefreshIntervalMs, subscribeConnection, subscribeState } from "./api";
import { CommandBar } from "./components/CommandBar";
import { HealthPanel } from "./components/HealthPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { LivePanel } from "./components/LivePanel";
import { LogsPanel } from "./components/LogsPanel";
import { PersistentFooter } from "./components/PersistentFooter";
import { PlaylistPanel } from "./components/PlaylistPanel";
import { QueuePanel } from "./components/QueuePanel";
import { SearchPanel } from "./components/SearchPanel";
import { StationPanel } from "./components/StationPanel";
import { GuestPanel } from "./components/GuestPanel";
import type { ControlState } from "./types";
import type { DjGooProfile } from "./api";
import { Onboarding } from "./components/Onboarding";
import { GamingSettings } from "./components/GamingSettings";
import { optimisticallyTogglePlayback, reconcilePlaybackState } from "./playbackClock";

const views = ["Live", "Find", "History", "Radio", "Lists", "Players", "Settings", "Logs"] as const;
type View = (typeof views)[number];

export function App() {
  const compact = new URLSearchParams(window.location.search).get("view") === "compact";
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("Ready");
  const [activeView, setActiveView] = useState<View>("Live");
  const [mobileDock, setMobileDock] = useState<"playlists" | "queue" | null>(null);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [profile, setProfile] = useState<DjGooProfile | null>(() => savedProfile());
  const refreshStarted = useRef(0);
  const refreshApplied = useRef(0);
  const role = isRemoteSession() ? (state?.session?.role || profile?.role || "guest") : "host";
  const canManage = role === "host" || role === "moderator";
  const visibleViews = views.filter((view) => canManage || !["Players", "Settings", "Logs"].includes(view));

  function navigate(view: View) {
    setActiveView(view);
    setMobileDock(null);
    setMobileMenu(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function refresh() {
    const requestNumber = ++refreshStarted.current;
    try {
      const next = await getState();
      if (requestNumber < refreshApplied.current) return next;
      refreshApplied.current = requestNumber;
      setState(current => reconcilePlaybackState(current, next));
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
      setState(current => reconcilePlaybackState(current, next));
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
      return <PlaylistPanel state={state} send={send} expanded canManage={canManage} refresh={refresh} />;
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
        <LivePanel state={state} send={send} openFind={() => navigate("Find")} />
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
              onClick={() => navigate(view)}
              type="button"
            >
              {view}
            </button>
          ))}
        </nav>}
        <section className="stack">
          {compact ? <LivePanel state={state} send={send} openFind={() => navigate("Find")} /> : renderView()}
        </section>
        {!compact && <aside className="side" data-open={mobileDock ? "true" : "false"}>
          <button className="mobile-dock-close" title="Close" aria-label="Close music drawer" onClick={() => setMobileDock(null)}><X size={20} /></button>
          <div className={mobileDock && mobileDock !== "playlists" ? "mobile-dock-hidden" : ""}><HealthPanel state={state} send={send} /><PlaylistPanel state={state} send={send} compact canManage={canManage} refresh={refresh} /></div>
          <div className={mobileDock && mobileDock !== "queue" ? "mobile-dock-hidden" : ""}><QueuePanel state={state} send={send} canManage={canManage} refresh={refresh} /></div>
        </aside>}
      </main>
      {!compact && mobileMenu && <>
        <button className="mobile-menu-backdrop" aria-label="Close navigation" onClick={() => setMobileMenu(false)} />
        <section className="mobile-more-menu" aria-label="More DjGoo pages">
          <div className="mobile-more-heading"><strong>More</strong><button className="icon-button" aria-label="Close navigation" onClick={() => setMobileMenu(false)}><X size={19} /></button></div>
          <div className="mobile-more-grid">
            {visibleViews.filter(view => !["Live", "Find", "Lists"].includes(view)).map(view => <button className={activeView === view ? "active" : ""} key={view} onClick={() => navigate(view)}>{view}</button>)}
            <button onClick={() => { setMobileMenu(false); setMobileDock("playlists"); }}>Playlists</button>
          </div>
        </section>
      </>}
      {!compact && <nav className="mobile-app-nav" aria-label="DjGoo mobile navigation">
        <button className={activeView === "Live" && !mobileDock ? "active" : ""} onClick={() => navigate("Live")}><House size={19} /><span>Live</span></button>
        <button className={activeView === "Find" && !mobileDock ? "active" : ""} onClick={() => navigate("Find")}><Search size={19} /><span>Find</span></button>
        <button className={mobileDock === "queue" ? "active" : ""} onClick={() => { setMobileMenu(false); setMobileDock(current => current === "queue" ? null : "queue"); }}><span className="queue-count">{state.queue.length}</span><span>Queue</span></button>
        <button className={activeView === "Lists" && !mobileDock ? "active" : ""} onClick={() => navigate("Lists")}><ListMusic size={19} /><span>Lists</span></button>
        <button className={mobileMenu || ["History", "Radio", "Players", "Settings", "Logs"].includes(activeView) ? "active" : ""} onClick={() => { setMobileDock(null); setMobileMenu(current => !current); }}><Menu size={19} /><span>More</span></button>
      </nav>}
      <PersistentFooter state={state} send={send} status={status} />
    </div>
  );
}
