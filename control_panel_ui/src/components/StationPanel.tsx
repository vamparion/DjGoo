import { useEffect, useState } from "react";
import { Play, Square, Trash2 } from "lucide-react";
import { stationAction } from "../api";
import type { PanelProps } from "./types";

type Props = PanelProps & { expanded?: boolean; canManage?: boolean };

export function StationPanel({ state, send, expanded = false, canManage = false }: Props) {
  const [stationId, setStationId] = useState(state.active_station?.id || state.stations[0]?.id || "");
  const [cloneName, setCloneName] = useState("");
  const station = state.stations.find((item) => item.id === stationId) || state.active_station || state.stations[0] || null;
  useEffect(() => { if (!stationId && state.stations[0]) setStationId(state.stations[0].id); }, [state.stations, stationId]);
  async function act(action: string, payload: Record<string, unknown> = {}) { if (!station) return; await stationAction(action, { seed: station.seed, ...payload }); }
  async function tune(key: string, value: number) { await act("settings", { settings: { [key]: value } }); }
  async function deleteStation() { if (!station || !window.confirm(`Delete "${station.name}" and its preferences?`)) return; await act("delete"); setStationId(state.stations.find((item) => item.id !== station.id)?.id || ""); }
  if (!station) return <section className="panel"><div className="empty-state"><strong>No radio stations yet</strong><p>Find a song, artist, album, decade, or genre and choose Radio.</p></div></section>;
  const active = state.active_station?.id === station.id;
  return <section className={`panel radio-panel ${expanded ? "wide-panel" : ""}`}>
    <div className="panel-title-row"><div><h2>Radio</h2><p>Shape what this station plays without managing every song.</p></div><div className="inline-actions"><button className="btn primary icon-action" onClick={() => void send("start_radio", { query: station.seed })}><Play size={15} /><span>{active ? "Restart" : "Start"}</span></button>{active && <button className="btn amber icon-action" onClick={() => void send("stop_radio")}><Square size={14} /><span>Stop radio</span></button>}</div></div>
    {expanded && <label className="station-picker">Station<select value={station.id} onChange={(event) => setStationId(event.target.value)}>{state.stations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
    <div className="station-summary"><div><span>Based on</span><strong>{station.seed}</strong></div><div><span>Played</span><strong>{station.played.length}</strong></div><div><span>Liked</span><strong>{station.liked_count}</strong></div><div><span>Blocked</span><strong>{station.banned_count}</strong></div></div>
    {expanded && <>
      <section className="radio-taste"><div><h3>Music mix</h3><p>Balance favorites with songs DjGoo has not played here before.</p></div><Tune label="Familiar music" value={station.familiar_percent} change={(value) => tune("familiar_percent", value)} /><Tune label="New discoveries" value={station.discovery_percent} change={(value) => tune("discovery_percent", value)} /></section>
      <div className="inline-actions radio-feedback"><button className="btn good" onClick={() => void act("undo", { feedback: "liked" })}>Undo last like</button><button className="btn" onClick={() => void act("undo", { feedback: "less_like" })}>Undo last dislike</button><button className="btn danger" onClick={() => void act("undo", { feedback: "banned" })}>Undo last ban</button></div>
      <div className="split"><History title="Recent station songs" items={station.recent.slice().reverse().slice(0, 10).map((item) => ({ title: item.title, detail: item.artist || "Played" }))} /><History title="Recent preferences" items={station.feedback_history.slice().reverse().slice(0, 10).map((item) => ({ title: item.track.title, detail: item.action.replace("_", " ") }))} /></div>
      <details className="subpanel advanced-radio"><summary>Advanced station settings</summary><div className="tuning-grid"><Tune label="Artist repeat spacing" value={station.artist_spacing} max={20} suffix=" songs" change={(value) => tune("artist_spacing", value)} /><Tune label="Song repeat spacing" value={station.song_spacing} max={200} suffix=" songs" change={(value) => tune("song_spacing", value)} /></div><div className="editor-row"><select value={station.seed_type} onChange={(event) => void act("settings", { settings: { seed_type: event.target.value } })}>{["auto", "song", "artist", "album", "playlist", "decade", "genre", "examples"].map((kind) => <option key={kind}>{kind}</option>)}</select><input defaultValue={station.seed_examples.join(", ")} placeholder="Additional artists or songs" onBlur={(event) => void act("settings", { settings: { seed_examples: event.target.value.split(",") } })} /></div><div className="inline-actions"><input value={cloneName} onChange={(event) => setCloneName(event.target.value)} placeholder="Copy name" /><button className="btn" disabled={!cloneName.trim()} onClick={() => void act("clone", { new_seed: cloneName })}>Copy station</button><button className="btn" onClick={() => void act("snapshot", { name: `Saved ${new Date().toLocaleString()}` })}>Save settings snapshot</button>{station.snapshots[0] && <button className="btn" onClick={() => void act("restore", { snapshot_id: station.snapshots.at(-1)?.id })}>Restore latest</button>}{canManage && <button className="btn danger icon-action" onClick={() => void deleteStation()}><Trash2 size={15} /><span>Delete station</span></button>}</div></details>
    </>}
  </section>;
}

function Tune({ label, value, change, max = 100, suffix = "%" }: { label: string; value: number; change: (value: number) => void; max?: number; suffix?: string }) { return <label className="tune"><span>{label}</span><input type="range" min={0} max={max} value={value} onChange={(event) => void change(Number(event.target.value))} /><strong>{value}{suffix}</strong></label>; }
function History({ title, items }: { title: string; items: Array<{ title: string; detail: string }> }) { return <div className="subpanel"><h3>{title}</h3>{items.length ? items.map((item, index) => <div className="compact-row" key={`${item.title}-${index}`}><strong>{item.title}</strong><span>{item.detail}</span></div>) : <p className="muted">Nothing recorded yet.</p>}</div>; }
