import type { ControlState } from "../types";
import type { CommandSender } from "./types";

type Props = {
  state: ControlState;
  send: CommandSender;
  status: string;
};

export function PersistentFooter({ state, send, status }: Props) {
  const title = state.playback.title || state.active_station?.last_track?.title || "DjGoo ready";

  return (
    <footer className="bottom">
      <button className="btn primary" onClick={() => void send("skip")}>Skip</button>
      <div className="mini-title">{status} | {title}</div>
      <div className="footer-actions">
        <button className="btn" onClick={() => void send("undo")}>Undo</button>
        <button className="btn good" onClick={() => void send("like")}>Like</button>
        <button className="btn" onClick={() => void send("less_like")}>Less Like</button>
        <button className="btn danger" onClick={() => void send("stop")}>Stop</button>
      </div>
    </footer>
  );
}
