import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { App } from "./App";
import { configureRemote } from "./api";
import { credentialWithInviteRoutes, inviteMatchesCredential, pairWeb, type WebCredential } from "./remoteTransport";

const SESSION_KEY = "djgoo-web-session";
const REMEMBER_KEY = "djgoo-web-remembered";
const PENDING_INVITE = "djgoo-pending-web-invite";

function completeInvitation() {
  sessionStorage.removeItem(PENDING_INVITE);
  localStorage.removeItem(PENDING_INVITE);
  if (window.location.hash) history.replaceState(null, "", window.location.pathname + window.location.search);
}

function storedCredential(): WebCredential | null {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(REMEMBER_KEY) || "null");
  } catch {
    return null;
  }
}

export function RemoteApp({ invite }: { invite: string }) {
  // Reopening the same one-time link must reuse its completed pairing. A link
  // for a rotated host route still supersedes the remembered credential.
  const [credential, setCredential] = useState<WebCredential | null>(() => {
    const stored = storedCredential();
    if (!stored) return null;
    if (!invite) return stored;
    return inviteMatchesCredential(invite, stored) ? credentialWithInviteRoutes(invite, stored) : null;
  });
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!credential) return;
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(credential));
    if (localStorage.getItem(REMEMBER_KEY)) localStorage.setItem(REMEMBER_KEY, JSON.stringify(credential));
    completeInvitation();
  }, [credential]);

  if (credential) {
    configureRemote(credential);
    return <App />;
  }

  if (!invite) {
    return (
      <main className="remote-shell remote-pairing">
        <section className="remote-pair">
          <div className="remote-brand-mark"><img src="./djgoo-mark.svg" alt="" /></div>
          <span className="remote-kicker">PRIVATE PLAYER ACCESS</span>
          <h1>Connect to DjGoo</h1>
          <p>In Discord, run <strong>/djgoo web</strong>, then open the new private link on this device.</p>
        </section>
      </main>
    );
  }

  async function connect() {
    try {
      setError("");
      const paired = await pairWeb(invite, navigator.userAgent.includes("Mobile") ? "DjGoo Web Mobile" : "DjGoo Web Browser");
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(paired.credential));
      if (remember) localStorage.setItem(REMEMBER_KEY, JSON.stringify(paired.credential));
      else localStorage.removeItem(REMEMBER_KEY);
      configureRemote(paired.credential);
      completeInvitation();
      setCredential(paired.credential);
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  }

  return (
    <main className="remote-shell remote-pairing">
      <section className="remote-pair">
        <div className="remote-brand-mark"><img src="./djgoo-mark.svg" alt="" /></div>
        <span className="remote-kicker">PRIVATE PLAYER ACCESS</span>
        <h1>Connect to DjGoo</h1>
        <p>Use the same DjGoo controls from this device.</p>
        <label><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /> Remember this device</label>
        <button className="remote-primary" onClick={() => void connect()}>Connect securely <ChevronRight size={18} /></button>
        {error && <p className="remote-error">{error}</p>}
      </section>
    </main>
  );
}
