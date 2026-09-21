import { useState } from "react";

type Props = { submit: (username: string) => Promise<void> };

export function Onboarding({ submit }: Props) {
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      await submit(username);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="onboarding">
      <section className="onboarding-panel">
        <div className="logo">DG</div>
        <div><h1>Choose your DjGoo name</h1><p>Your requests, votes, and queue position will use this name.</p></div>
        <input autoFocus maxLength={32} placeholder="Player name" value={username} onChange={(event) => setUsername(event.target.value)} onKeyDown={(event) => event.key === "Enter" && void save()} />
        {error && <div className="error">{error}</div>}
        <button className="btn primary" disabled={busy || username.trim().length < 2} onClick={() => void save()}>{busy ? "Joining..." : "Enter DjGoo"}</button>
      </section>
    </main>
  );
}
