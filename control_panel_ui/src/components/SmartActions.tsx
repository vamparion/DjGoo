import type { PanelProps } from "./types";

type Props = PanelProps & {
  mode?: "live" | "radio";
};

export function SmartActions({ send, mode = "live" }: Props) {
  const radioMode = mode === "radio";
  return (
    <section className="smart-row">
      <div className="smart">
        <strong>{radioMode ? "Shape this station" : "One-tap playlist add"}</strong>
        <p>{radioMode ? "Every rating stays local to this station." : "Current track goes to your most-used lists."}</p>
        <button className="btn" onClick={() => void send("save_current", { playlist: "chill" })}>Chill</button>
        <button className="btn" onClick={() => void send("save_current", { playlist: "80s" })}>80s</button>
      </div>
      <div className="smart">
        <strong>Fix bad radio</strong>
        <p>Ban current, skip it, and let station mode replace it.</p>
        <button className="btn danger" onClick={() => void send("ban")}>Ban + Replace</button>
      </div>
      <div className="smart">
        <strong>{radioMode ? "Stop station cleanly" : "Quick radio starts"}</strong>
        <p>{radioMode ? "Stop means stop; it should not auto-resume after a song request." : "Start common moods without typing."}</p>
        {radioMode ? (
          <button className="btn amber" onClick={() => void send("stop_radio")}>Stop Radio</button>
        ) : (
          <button className="btn primary" onClick={() => void send("start_radio", { query: "80s" })}>80s Radio</button>
        )}
      </div>
      <div className="smart">
        <strong>Recovery</strong>
        <p>Restart Redbot, voice listener, and resume only on reset.</p>
        <button className="btn danger" onClick={() => void send("reset")}>Reset DjGoo</button>
      </div>
    </section>
  );
}
