import { useEffect, useState } from "react";
import { getAudioInputs, isRemoteSession, saveAudioInput, saveGamingSettings, type AudioInput } from "../api";
import type { ControlState } from "../types";

type Props = { state: ControlState; refresh: () => Promise<void>; host: boolean };

export function GamingSettings({ state, refresh, host }: Props) {
  const [busy, setBusy] = useState(false);
  const [inputs, setInputs] = useState<AudioInput[]>([]);
  const [microphone, setMicrophone] = useState("");
  const [voiceStatus, setVoiceStatus] = useState("");
  const settings = state.gaming.settings;
  useEffect(() => {
    if (isRemoteSession() || !host) return;
    void getAudioInputs().then((data) => {
      setInputs(data.devices);
      const preferred = data.devices.find((item) => item.available && item.name.includes("Arctis Nova 7")) || data.devices.find((item) => item.available);
      if (preferred) setMicrophone(preferred.name);
    }).catch((error) => setVoiceStatus(String(error.message || error)));
  }, [host]);
  async function update(key: string, value: unknown) {
    setBusy(true);
    try { await saveGamingSettings({ [key]: value }); await refresh(); } finally { setBusy(false); }
  }
  async function threshold(action: string, value: number) {
    await update("vote_thresholds", { ...settings.vote_thresholds, [action]: value });
  }
  return (
    <section className="panel settings-panel">
      <div className="panel-title-row"><div><h2>Gaming Policy</h2><p>Host controls applied to Discord, voice, desktop, and phones.</p></div><span className="role-badge">{host ? "Host" : "View only"}</span></div>
      <div className="settings-grid">
        {!isRemoteSession() && <label className="wide-setting"><span>Voice control input</span><select value={microphone} disabled={!host || busy} onChange={(event) => setMicrophone(event.target.value)}><option value="">Choose a microphone</option>{inputs.map((item) => <option key={`${item.id}-${item.name}`} value={item.name} disabled={!item.available}>{item.name}{item.default ? " (Windows default)" : ""}{!item.available ? " (unavailable)" : ""}</option>)}</select><button className="btn primary" disabled={!microphone || busy} onClick={async () => { setBusy(true); setVoiceStatus("Applying microphone..."); try { await saveAudioInput(microphone); setVoiceStatus("Saved. DjGoo is reconnecting Voice Control."); } catch (error) { setVoiceStatus(String((error as Error).message || error)); } finally { setBusy(false); } }}>Use Microphone</button>{voiceStatus && <small>{voiceStatus}</small>}</label>}
        <label><span>Ranked mode</span><input type="checkbox" checked={settings.ranked_mode} disabled={!host || busy} onChange={(e) => void update("ranked_mode", e.target.checked)} /></label>
        <label><span>Fair rotation</span><input type="checkbox" checked={settings.round_robin} disabled={!host || busy} onChange={(e) => void update("round_robin", e.target.checked)} /></label>
        <label><span>Requests per player</span><input type="number" min={1} max={25} value={settings.per_user_queue_limit} disabled={!host || busy} onChange={(e) => void update("per_user_queue_limit", Number(e.target.value))} /></label>
        {(["skip", "more_like", "less_like", "ban"] as const).map((action) => <label key={action}><span>{action.replace("_", " ")} votes</span><input type="number" min={1} max={20} value={settings.vote_thresholds[action]} disabled={!host || busy} onChange={(e) => void threshold(action, Number(e.target.value))} /></label>)}
        <label><span>Explicit tracks</span><select value={settings.explicit_policy} disabled={!host || busy} onChange={(e) => void update("explicit_policy", e.target.value)}><option value="allow">Allow</option><option value="warn">Warn</option><option value="reject">Reject</option></select></label>
        <label><span>Normalize volume</span><input type="checkbox" checked={settings.volume_normalization} disabled={!host || busy} onChange={(e) => void update("volume_normalization", e.target.checked)} /></label>
        <label><span>Target volume</span><input type="number" min={20} max={150} value={settings.normalization_target} disabled={!host || busy} onChange={(e) => void update("normalization_target", Number(e.target.value))} /></label>
        <label><span>Fade transitions</span><input type="checkbox" checked={settings.crossfade_enabled} disabled={!host || busy} onChange={(e) => void update("crossfade_enabled", e.target.checked)} /></label>
        <label><span>Fade seconds</span><input type="number" min={1} max={10} value={settings.crossfade_seconds} disabled={!host || busy} onChange={(e) => void update("crossfade_seconds", Number(e.target.value))} /></label>
        <label><span>Preload radio</span><input type="checkbox" checked={settings.preload_enabled} disabled={!host || busy} onChange={(e) => void update("preload_enabled", e.target.checked)} /></label>
        <label><span>Media keys</span><input type="checkbox" checked={settings.media_keys_enabled} disabled={!host || busy} onChange={(e) => void update("media_keys_enabled", e.target.checked)} /></label>
      </div>
    </section>
  );
}
