import { X } from "lucide-react";
import type { PanelProps } from "./types";
import { QueuePanel } from "./QueuePanel";

export function QueueModal({ state, send, close }: PanelProps & { close: () => void }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <section className="queue-modal" role="dialog" aria-modal="true" aria-label="Playback queue">
        <button className="modal-close" onClick={close} title="Close queue" aria-label="Close queue"><X size={20} /></button>
        <QueuePanel state={state} send={send} />
      </section>
    </div>
  );
}
