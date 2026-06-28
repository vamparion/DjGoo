import { useState } from "react";
import type { CommandSender } from "./types";

type Props = {
  send: CommandSender;
};

export function CommandBar({ send }: Props) {
  const [query, setQuery] = useState("");
  const [action, setAction] = useState("auto");

  async function submit() {
    const text = query.trim();
    if (!text) return;
    if (action === "start_radio") {
      await send("start_radio", { query: text });
    } else if (action === "add_to_playlist") {
      await send("save_current", { playlist: text });
    } else {
      await send(action === "auto" ? "play_next" : action, { query: text });
    }
    setQuery("");
  }

  return (
    <header className="topbar">
      <div className="brand">
        <div className="logo">DG</div>
        <div>DjGoo</div>
      </div>
      <div className="command">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void submit();
          }}
          placeholder="Type once: play song, radio 80s, add current to chill, ban this"
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
      <button className="btn danger" onClick={() => void send("stop")}>
        Panic Stop
      </button>
    </header>
  );
}
