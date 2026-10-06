import type { ControlState } from "../types";
import type { CommandSender } from "./types";
import { ListMusic, Pause, Play, SkipForward, Square } from "lucide-react";

type Props = {
  state: ControlState;
  send: CommandSender;
  status: string;
};

export function PersistentFooter({ state, send, status }: Props) {
  const title = state.playback.title || state.active_station?.last_track?.title || "DjGoo ready";

  return (
    <footer className="bottom" onDragOver={(event) => { if (event.dataTransfer.types.includes("application/djgoo-track")) event.preventDefault(); }} onDrop={(event) => { const raw = event.dataTransfer.getData("application/djgoo-track"); if (raw) void send("play_next", { query: JSON.parse(raw).uri }); }}>
      <img className="footer-art" src={state.playback.artwork_url || "./icons/djgoo-192.png"} alt="" />
      <div className="mini-title"><strong>{title}</strong><span>{state.playback.artist || status}</span></div>
      <div className="footer-actions">
        <button className="icon-button" title={state.playback.playing ? "Pause" : "Resume"} onClick={() => void send("toggle_pause")}>{state.playback.playing ? <Pause size={17} /> : <Play size={17} />}</button>
        <button className="icon-button" title="Skip" onClick={() => void send("skip")}><SkipForward size={17} /></button>
        <button className="icon-button" title="Queue" onClick={() => void send("queue")}><ListMusic size={17} /></button>
        <button className="icon-button danger" title="Stop and clear queue" onClick={() => void send("stop")}><Square size={15} /></button>
      </div>
    </footer>
  );
}
