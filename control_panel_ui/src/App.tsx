import { useEffect, useState } from "react";
import { getState } from "./api";
import type { ControlState } from "./types";

export function App() {
  const [state, setState] = useState<ControlState | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getState().then(setState).catch((err) => setError(String(err.message || err)));
  }, []);

  return (
    <main className="appShell">
      <h1>DjGoo Control</h1>
      {error && <p className="error">{error}</p>}
      <pre>{JSON.stringify(state, null, 2)}</pre>
    </main>
  );
}
