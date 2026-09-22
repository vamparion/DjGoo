import { useState } from "react";
import { searchLibrary, searchNuclear } from "../api";
import type { PanelProps } from "./types";

const quickSearches = ["sandstorm", "80s hits", "rocket league edm", "white girl music", "linkin park", "chill radio"];

export function SearchPanel({ send }: PanelProps) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [library, setLibrary] = useState<Array<Record<string, unknown>>>([]);

  async function preview(text = query) {
    const q = text.trim();
    if (!q) return;
    setBusy(true);
    try {
      const data = await searchNuclear(q);
      setResult(data.result || "No strong Nuclear match yet. Use Play Next to let DjGoo resolve it.");
    } catch (err) {
      setResult(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }
  async function findEverywhere() { const q = query.trim(); if (!q) return; const data = await searchLibrary(q); setLibrary(data.results); }

  async function submit(action: "play" | "play_next" | "start_radio") {
    const q = query.trim();
    if (!q) return;
    await send(action, { query: q });
    setQuery("");
  }

  return (
    <section className="panel search-panel">
      <div className="panel-title-row">
        <div>
          <h2>Find Music Fast</h2>
          <p>Search once, then play now, play next, or turn it into a station.</p>
        </div>
        <button className="btn" onClick={() => void preview()} disabled={busy}>
          {busy ? "Checking" : "Preview"}
        </button>
      </div>
      <div className="large-command">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void submit("play_next");
          }}
          placeholder="Song, artist, album, mood, or station seed"
        />
        <button className="btn primary" onClick={() => void submit("play_next")}>Play Next</button>
        <button className="btn" onClick={() => void submit("play")}>Play Now</button>
        <button className="btn amber" onClick={() => void submit("start_radio")}>Radio</button>
        <button className="btn" onClick={() => void findEverywhere()}>My Library</button>
      </div>
      {result && (
        <div className="result-box">
          <span>Nuclear preview</span>
          <strong>{result}</strong>
        </div>
      )}
      {library.length > 0 && <div className="list">{library.slice(0, 20).map((item, index) => <div className="row" key={`${String(item.uri)}-${index}`}><div><strong>{String(item.title || "Untitled")}</strong><span>{String(item.kind)} · {String(item.group)}</span></div><button className="btn" onClick={() => void send("play_next", { query: String(item.uri || item.title) })}>Next</button></div>)}</div>}
      <div className="chip-row">
        {quickSearches.map((item) => (
          <button
            className="chip"
            key={item}
            onClick={() => {
              setQuery(item);
              void preview(item);
            }}
          >
            {item}
          </button>
        ))}
      </div>
    </section>
  );
}
