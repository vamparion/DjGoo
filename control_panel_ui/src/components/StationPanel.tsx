import { useEffect, useState } from "react";
import { stationAction } from "../api";
import type { PanelProps } from "./types";

type Props = PanelProps & { expanded?: boolean };

export function StationPanel({ state, send, expanded = false }: Props) {
  const [stationId, setStationId] = useState(state.active_station?.id || state.stations[0]?.id || "");
  const [cloneName, setCloneName] = useState("");
  const [mergeSeeds, setMergeSeeds] = useState("");
  const [mergeName, setMergeName] = useState("");
  const station = state.stations.find((item) => item.id === stationId) || state.active_station || state.stations[0] || null;
  useEffect(() => { if (!stationId && state.stations[0]) setStationId(state.stations[0].id); }, [state.stations, stationId]);
  async function act(action: string, payload: Record<string, unknown> = {}) { if (!station) return; await stationAction(action, { seed: station.seed, ...payload }); await send("queue"); }
  async function tune(key: string, value: number) { await act("settings", { settings: { [key]: value } }); }
  if (!station) return <section className="panel"><div className="empty-state"><strong>No station yet</strong><p>Start with a song, artist, album, playlist, decade, genre, or several examples.</p><button className="btn primary" onClick={() => void send("start_radio", { query: "80s" })}>Start 80s Radio</button></div></section>;
  return <section className={`panel ${expanded ? "wide-panel" : ""}`}>
    <div className="panel-title-row"><div><h2>Radio Studio</h2><p>{station.last_selection_reason || `Tuned around ${station.seed}`}</p></div><div className="inline-actions"><button className="btn" onClick={() => void send("start_radio", { query: station.seed })}>Start</button><button className="btn amber" onClick={() => void send("stop_radio")}>Stop Radio</button></div></div>
    {expanded && <select value={station.id} onChange={(event) => setStationId(event.target.value)}>{state.stations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
    <div className="metric-grid"><div className="metric"><span>Seed type</span><strong>{station.seed_type}</strong></div><div className="metric"><span>Drift</span><strong>{station.last_drift_score || 0}%</strong></div><div className="metric"><span>Played here</span><strong>{station.played.length}</strong></div><div className="metric"><span>Preferences</span><strong>{station.feedback_history.length}</strong></div></div>
    {expanded && <><div className="tuning-grid"><Tune label="Familiar" value={station.familiar_percent} change={(value) => tune("familiar_percent", value)} /><div className="metric"><span>Balanced</span><strong>{station.balanced_percent}%</strong></div><Tune label="Discovery" value={station.discovery_percent} change={(value) => tune("discovery_percent", value)} /><Tune label="Artist spacing" value={station.artist_spacing} max={20} suffix=" songs" change={(value) => tune("artist_spacing", value)} /><Tune label="Song spacing" value={station.song_spacing} max={200} suffix=" songs" change={(value) => tune("song_spacing", value)} /></div>
      <div className="inline-actions"><button className="btn good" onClick={() => void act("undo", { feedback: "liked" })}>Undo Like</button><button className="btn" onClick={() => void act("undo", { feedback: "less_like" })}>Undo Dislike</button><button className="btn danger" onClick={() => void act("undo", { feedback: "banned" })}>Undo Ban</button><button className="btn" onClick={() => void act("snapshot", { name: `Before changes ${new Date().toLocaleTimeString()}` })}>Save Snapshot</button></div>
      <div className="split"><History title="Preference history" items={station.feedback_history.slice().reverse().slice(0, 12).map((item) => ({ title: item.track.title, detail: item.action.replace("_", " ") }))} /><History title="Station history" items={station.recent.slice().reverse().slice(0, 12).map((item) => ({ title: item.title, detail: item.artist || "Played" }))} /></div>
      <div className="editor-row"><select value={station.seed_type} onChange={(event) => void act("settings", { settings: { seed_type: event.target.value } })}>{["auto", "song", "artist", "album", "playlist", "decade", "genre", "examples"].map((kind) => <option key={kind}>{kind}</option>)}</select><input defaultValue={station.seed_examples.join(", ")} placeholder="Multiple seed examples" onBlur={(event) => void act("settings", { settings: { seed_examples: event.target.value.split(",") } })} /></div>
      <div className="editor-row"><input value={cloneName} onChange={(event) => setCloneName(event.target.value)} placeholder="New station name" /><button className="btn" onClick={() => void act("clone", { new_seed: cloneName })}>Clone Without History</button>{station.snapshots[0] && <button className="btn" onClick={() => void act("restore", { snapshot_id: station.snapshots.at(-1)?.id })}>Restore Latest Snapshot</button>}</div>
      <div className="editor-row"><input value={mergeSeeds} onChange={(event) => setMergeSeeds(event.target.value)} placeholder="Stations to merge, comma separated" /><input value={mergeName} onChange={(event) => setMergeName(event.target.value)} placeholder="Merged station name" /><button className="btn" onClick={() => void stationAction("merge", { seed: station.seed, seeds: mergeSeeds.split(","), new_seed: mergeName }).then(() => send("queue"))}>Merge Into New Station</button></div></>}
  </section>;
}

function Tune({ label, value, change, max = 100, suffix = "%" }: { label: string; value: number; change: (value: number) => void; max?: number; suffix?: string }) { return <label className="tune"><span>{label}</span><input type="range" min={0} max={max} value={value} onChange={(event) => void change(Number(event.target.value))} /><strong>{value}{suffix}</strong></label>; }
function History({ title, items }: { title: string; items: Array<{ title: string; detail: string }> }) { return <div className="subpanel"><h3>{title}</h3>{items.length ? items.map((item, index) => <div className="compact-row" key={`${item.title}-${index}`}><strong>{item.title}</strong><span>{item.detail}</span></div>) : <p className="muted">Nothing recorded yet.</p>}</div>; }
