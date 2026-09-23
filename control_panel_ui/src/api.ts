import type { ControlState } from "./types";
import { remoteCommand, remoteState, type WebCredential } from "./remoteTransport";

const API_BASE = import.meta.env.VITE_DJGOO_API_BASE || "";
const PROFILE_KEY = "djgoo-profile";
let remoteCredential: WebCredential | null = null;
let remoteProfile: DjGooProfile | null = null;

export type DjGooProfile = { id: string; token: string; username: string; role: string };

export function configureRemote(credential: WebCredential, profile?: Partial<DjGooProfile>) {
  remoteCredential = credential;
  remoteProfile = {
    id: credential.discord_user_id,
    token: credential.device_token,
    username: profile?.username || "Discord member",
    role: profile?.role || "member",
  };
}

export function updateRemoteProfile(profile: Partial<DjGooProfile>) {
  if (remoteProfile) remoteProfile = { ...remoteProfile, ...profile };
}

export function isRemoteSession() { return Boolean(remoteCredential); }

export function forgetRemoteSession() {
  remoteCredential = null;
  remoteProfile = null;
  window.sessionStorage.removeItem("djgoo-web-session");
  window.localStorage.removeItem("djgoo-web-remembered");
}

export function savedProfile(): DjGooProfile | null {
  if (remoteProfile) return remoteProfile;
  try {
    return JSON.parse(window.localStorage.getItem(PROFILE_KEY) || "null");
  } catch {
    return null;
  }
}

export async function createProfile(username: string): Promise<DjGooProfile> {
  const deviceId = window.localStorage.getItem("djgoo-device") || crypto.randomUUID();
  window.localStorage.setItem("djgoo-device", deviceId);
  const data = await request<{ ok: true; profile: DjGooProfile }>("/api/profile", {
    method: "POST",
    body: JSON.stringify({ username, device_id: deviceId }),
  });
  window.localStorage.setItem(PROFILE_KEY, JSON.stringify(data.profile));
  return data.profile;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const text = await response.text();
  let data: any;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(text.trimStart().startsWith("<")
      ? "DjGoo received a webpage instead of control data. Reload the app and try again."
      : `DjGoo received an invalid control response (${response.status}).`);
  }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data as T;
}

export async function getState(): Promise<ControlState> {
  if (remoteCredential) {
    const state = await remoteState(remoteCredential) as ControlState;
    const session = state.session;
    if (session) updateRemoteProfile({ username: session.display_name, role: session.role });
    return state;
  }
  const data = await request<{ ok: true; state: ControlState }>("/api/state");
  return data.state;
}

export async function sendCommand(action: string, payload: Record<string, unknown> = {}) {
  if (remoteCredential) return remoteCommand(remoteCredential, remoteIntent(action), payload);
  const profile = savedProfile();
  return request<{ ok: true; item: unknown }>("/api/command", {
    method: "POST",
    body: JSON.stringify({ action, token: profile?.token || "", ...payload }),
  });
}

export async function saveGamingSettings(settings: Record<string, unknown>) {
  if (remoteCredential) return remoteCommand(remoteCredential, "remote_settings", { payload: { settings } });
  const profile = savedProfile();
  return request<{ ok: true; settings: unknown }>("/api/settings", {
    method: "POST",
    body: JSON.stringify({ token: profile?.token || "", settings }),
  });
}

export async function setPlayerRole(profileId: string, role: string) {
  if (remoteCredential) return remoteCommand(remoteCredential, "remote_player_role", { payload: { profile_id: profileId, role } });
  const profile = savedProfile();
  return request<{ ok: true; profile: unknown }>("/api/profile/role", {
    method: "POST",
    body: JSON.stringify({ token: profile?.token || "", profile_id: profileId, role }),
  });
}

export async function stationAction(action: string, payload: Record<string, unknown>) {
  if (remoteCredential) return remoteCommand(remoteCredential, "remote_station_action", { payload: { action, ...payload } });
  const profile = savedProfile();
  return request<{ ok: true; result: unknown }>(`/api/station/${action}`, { method: "POST", body: JSON.stringify({ token: profile?.token || "", ...payload }) });
}

export async function playlistAction(action: string, payload: Record<string, unknown>) {
  if (remoteCredential) return remoteCommand(remoteCredential, "remote_playlist_action", { payload: { action, ...payload } });
  const profile = savedProfile();
  return request<{ ok: true; result: unknown }>(`/api/playlist/${action}`, { method: "POST", body: JSON.stringify({ token: profile?.token || "", ...payload }) });
}

export async function searchLibrary(query: string) {
  if (remoteCredential) {
    const state = await getState();
    const needle = query.toLocaleLowerCase();
    const results: Array<Record<string, unknown>> = [];
    state.playlists.forEach(list => list.tracks.forEach(track => {
      if (`${track.title} ${track.artist || ""} ${list.name}`.toLocaleLowerCase().includes(needle)) results.push({ kind: "playlist", group: list.name, ...track });
    }));
    state.stations.forEach(station => station.played.forEach(track => {
      if (`${track.title} ${track.artist || ""} ${station.name}`.toLocaleLowerCase().includes(needle)) results.push({ kind: "station", group: station.name, ...track });
    }));
    return { ok: true as const, results: results.slice(0, 100) };
  }
  return request<{ ok: true; results: Array<Record<string, unknown>> }>(`/api/library/search?q=${encodeURIComponent(query)}`);
}

export async function downloadBackup() {
  const data = remoteCredential
    ? { ok: true as const, backup: await getState() }
    : await request<{ ok: true; backup: unknown }>("/api/backup");
  const blob = new Blob([JSON.stringify(data.backup, null, 2)], { type: "application/json" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `djgoo-backup-${new Date().toISOString().slice(0, 10)}.json`; link.click(); URL.revokeObjectURL(link.href);
}

export async function searchNuclear(query: string) {
  if (remoteCredential) return { ok: true as const, query, result: "Use Play Next to have DjGoo resolve the cleanest match." };
  return request<{ ok: true; query: string; result: string | null }>(`/api/search?q=${encodeURIComponent(query)}`);
}

export async function resetDjGoo() {
  if (remoteCredential) throw new Error("Recovery is available from the Windows Control Center.");
  return request<{ ok: true }>("/api/system/reset", { method: "POST", body: "{}" });
}

export type AudioInput = { id: number; name: string; available: boolean; default: boolean; error?: string };

export async function getAudioInputs() {
  if (remoteCredential) return { ok: true as const, devices: [] as AudioInput[], selected: "" };
  return request<{ ok: true; devices: AudioInput[]; default_id: number }>("/api/audio-inputs");
}

export async function saveAudioInput(name: string) {
  if (remoteCredential) throw new Error("Microphone selection is available on the host control panel.");
  const profile = savedProfile();
  return request<{ ok: true; input_device: string }>("/api/audio-input", {
    method: "POST",
    body: JSON.stringify({ token: profile?.token || "", name }),
  });
}

function remoteIntent(action: string) {
  const mapped: Record<string, string> = {
    play_next: "play",
    toggle_pause: "toggle_pause",
    like: "station_like_current",
    more_like: "station_more_like_current",
    less_like: "station_less_like_current",
    ban: "station_ban_current",
    save_current: "mini_playlist_add_current",
    remove_queue: "mini_queue_remove",
    undo: "mini_queue_undo",
  };
  return mapped[action] || action;
}
