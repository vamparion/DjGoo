import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { App } from "./App";
import { configureRemote } from "./api";
import { pairWeb, type WebCredential } from "./remoteTransport";

const SESSION_KEY = "djgoo-web-session";
const REMEMBER_KEY = "djgoo-web-remembered";

function storedCredential(): WebCredential | null {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(REMEMBER_KEY) || "null");
  } catch {
    return null;
  }
}

export function RemoteApp({ invite }: { invite: string }) {
  // A fresh invite always supersedes a remembered route. This is essential
  // when the Host rotates a revoked webhook into its private transport channel.
  const [credential, setCredential] = useState<WebCredential | null>(() => invite ? null : storedCredential());
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");

  if (credential) {
    configureRemote(credential);
    return <App />;
  }

  async function connect() {
    try {
      setError("");
      const paired = await pairWeb(invite, navigator.userAgent.includes("Mobile") ? "DjGoo Web Mobile" : "DjGoo Web Browser");
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(paired.credential));
      if (remember) localStorage.setItem(REMEMBER_KEY, JSON.stringify(paired.credential));
      configureRemote(paired.credential);
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
