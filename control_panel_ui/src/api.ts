import type { ControlState } from "./types";

const API_BASE = import.meta.env.VITE_DJGOO_API_BASE || "";
const PROFILE_KEY = "djgoo-profile";

export type DjGooProfile = { id: string; token: string; username: string; role: string };

export function savedProfile(): DjGooProfile | null {
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
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data as T;
}

export async function getState(): Promise<ControlState> {
  const data = await request<{ ok: true; state: ControlState }>("/api/state");
  return data.state;
}

export async function sendCommand(action: string, payload: Record<string, unknown> = {}) {
  const profile = savedProfile();
  return request<{ ok: true; item: unknown }>("/api/command", {
    method: "POST",
    body: JSON.stringify({ action, token: profile?.token || "", ...payload }),
  });
}

export async function saveGamingSettings(settings: Record<string, unknown>) {
  const profile = savedProfile();
  return request<{ ok: true; settings: unknown }>("/api/settings", {
    method: "POST",
    body: JSON.stringify({ token: profile?.token || "", settings }),
  });
}

export async function setPlayerRole(profileId: string, role: string) {
  const profile = savedProfile();
  return request<{ ok: true; profile: unknown }>("/api/profile/role", {
    method: "POST",
    body: JSON.stringify({ token: profile?.token || "", profile_id: profileId, role }),
  });
}

export async function searchNuclear(query: string) {
  return request<{ ok: true; query: string; result: string | null }>(`/api/search?q=${encodeURIComponent(query)}`);
}

export async function resetDjGoo() {
  return request<{ ok: true }>("/api/system/reset", { method: "POST", body: "{}" });
}
