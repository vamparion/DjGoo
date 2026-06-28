import type { PanelProps } from "./types";

export function SmartActions({ send }: PanelProps) {
  return (
    <section className="smart-row">
      <div className="smart">
        <strong>One-tap playlist add</strong>
        <p>Current track goes to your most-used lists.</p>
        <button className="btn" onClick={() => void send("save_current", { playlist: "chill" })}>Chill</button>
        <button className="btn" onClick={() => void send("save_current", { playlist: "80s" })}>80s</button>
      </div>
      <div className="smart">
        <strong>Fix bad radio</strong>
        <p>Ban current, skip it, and let station mode replace it.</p>
        <button className="btn danger" onClick={() => void send("ban")}>Ban + Replace</button>
      </div>
      <div className="smart">
        <strong>Guest requests</strong>
        <p>Guest mode lands here after local admin is stable.</p>
        <button className="btn primary" disabled>Approve Next</button>
      </div>
      <div className="smart">
        <strong>Recovery</strong>
        <p>Restart Redbot, voice listener, and resume only on reset.</p>
        <button className="btn danger" onClick={() => void send("reset")}>Reset DjGoo</button>
      </div>
    </section>
  );
}
