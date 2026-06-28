import type { ControlState } from "./types";

const API_BASE = import.meta.env.VITE_DJGOO_API_BASE || "";

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
  return request<{ ok: true; item: unknown }>("/api/command", {
    method: "POST",
    body: JSON.stringify({ action, ...payload }),
  });
}

export async function searchNuclear(query: string) {
  return request<{ ok: true; query: string; result: string | null }>(`/api/search?q=${encodeURIComponent(query)}`);
}

export async function resetDjGoo() {
  return request<{ ok: true }>("/api/system/reset", { method: "POST", body: "{}" });
}
