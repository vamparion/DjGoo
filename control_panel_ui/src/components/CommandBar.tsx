import { useState } from "react";
import type { CommandSender } from "./types";

type Props = {
  send: CommandSender;
};

export function CommandBar({ send }: Props) {
  const [query, setQuery] = useState("");
  const [action, setAction] = useState("auto");

  function resolveAutoAction(text: string) {
    const lower = text.toLowerCase();
    if (lower.startsWith("radio ")) return { action: "start_radio", query: text.slice(6).trim() };
    if (lower.startsWith("play ")) return { action: "play_next", query: text.slice(5).trim() };
    if (lower.startsWith("save ") || lower.startsWith("add ")) return { action: "save_current", playlist: text.replace(/^(save|add)\s+/i, "").trim() };
    if (["skip", "stop", "queue", "pause", "resume"].includes(lower)) return { action: lower, query: "" };
    return { action: "play_next", query: text };
  }

  async function submit() {
    const text = query.trim();
    if (!text) return;
    if (action === "auto") {
      const resolved = resolveAutoAction(text);
      await send(resolved.action, { query: resolved.query, playlist: resolved.playlist });
    } else if (action === "start_radio") {
      await send("start_radio", { query: text.replace(/^radio\s+/i, "") });
    } else if (action === "add_to_playlist") {
      await send("save_current", { playlist: text });
    } else {
      await send(action, { query: text.replace(/^play\s+/i, "") });
    }
    setQuery("");
  }

  return (
    <header className="topbar">
      <div className="brand">
        <div className="logo">DG</div>
        <div>
          <strong>DjGoo</strong>
          <span>Control Panel</span>
        </div>
      </div>
      <div className="command">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void submit();
          }}
          placeholder="Command: play song, radio 80s, save chill"
        />
        <select value={action} onChange={(event) => setAction(event.target.value)}>
          <option value="auto">Auto action</option>
          <option value="play">Play now</option>
          <option value="play_next">Play next</option>
          <option value="add_to_playlist">Add current to playlist</option>
          <option value="start_radio">Start radio</option>
        </select>
        <button className="btn primary" onClick={() => void submit()}>
          Go
        </button>
      </div>
      <div className="top-actions">
        <button className="btn" onClick={() => void send("queue")}>Queue</button>
        <button className="btn danger" onClick={() => void send("stop")}>Stop</button>
      </div>
    </header>
  );
}
