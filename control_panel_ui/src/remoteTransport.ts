import { chacha20poly1305 } from "@noble/ciphers/chacha.js";
import { x25519 } from "@noble/curves/ed25519.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { hkdf } from "@noble/hashes/hkdf.js";

const enc = new TextEncoder();
const dec = new TextDecoder();
const REQUEST = "DJGOO-LINK-1:";
const RESPONSE = "DJGOO-LINK-1-RESPONSE:";
const RESPONSE_ATTACHMENT = "DJGOO-LINK-1-ATTACHMENT:";
const MAX_CONTENT = 1950;

type BrowserTransport = "relay" | "discord";
type Endpoint = { transport: string; endpoint: string; security: string; code: string; room_id: string; host_public_key: string };
export type WebRoute = { transport: BrowserTransport; endpoint: string };
export type WebCredential = {
  transport?: BrowserTransport;
  routes?: WebRoute[];
  webhook_url?: string;
  relay_url?: string;
  room_id: string;
  host_public_key: string;
  host_fingerprint: string;
  device_id: string;
  device_token: string;
  discord_user_id: string;
  guild_id: string;
  device_type: string;
  capabilities: string[];
};

type ExchangeContext = {
  requestId: string;
  secret: Uint8Array;
  salt: Uint8Array;
  envelope: Record<string, unknown>;
  roomId: string;
};

const b64d = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - s.length % 4) % 4)), c => c.charCodeAt(0));
const b64e = (b: Uint8Array) => btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const hex = (b: Uint8Array) => [...b].map(x => x.toString(16).padStart(2, "0")).join("");

async function discordJson(response: Response, operation: string): Promise<Record<string, any>> {
  const text = await response.text();
  try {
    const value = JSON.parse(text);
    if (value && typeof value === "object") return value;
  } catch {
    // Convert proxy, captive-portal, and stale-cache HTML into a useful error.
  }
  const received = text.trimStart().startsWith("<") ? "a webpage" : "an invalid response";
  throw new Error(`Discord returned ${received} while ${operation}. Refresh DjGoo and try the newest link.`);
}

function discordUrlCandidates(url: string): string[] {
  const parsed = new URL(url);
  const hosts = [parsed.hostname, "discord.com", "discordapp.com", "canary.discord.com"];
  return [...new Set(hosts)].map(host => {
    const candidate = new URL(parsed.toString());
    candidate.hostname = host;
    return candidate.toString();
  });
}

async function pollDiscordMessage(url: string): Promise<Response | null> {
  for (const candidate of discordUrlCandidates(url)) {
    try {
      const response = await fetch(candidate, { cache: "no-store" });
      if (response.status !== 429 && response.status < 500) return response;
    } catch {
      // Mobile networks and Discord edges can drop an individual CORS fetch.
      // Continue polling the same encrypted message through another API edge.
    }
  }
  return null;
}

async function createDiscordMessage(url: string, body: string): Promise<Response | null> {
  let lastResponse: Response | null = null;
  for (const candidate of discordUrlCandidates(url)) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await fetch(candidate + (candidate.includes("?") ? "&wait=true" : "?wait=true"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          cache: "no-store",
        });
        lastResponse = response;
        if (response.status !== 429 && response.status < 500) return response;
        const limited = await response.clone().json().catch(() => ({}));
        const retrySeconds = Math.max(0.5, Math.min(8, Number(limited.retry_after || 1)));
        await new Promise(resolve => setTimeout(resolve, retrySeconds * 1000));
      } catch {
        await new Promise(resolve => setTimeout(resolve, 350 * (attempt + 1)));
      }
    }
  }
  return lastResponse;
}

function validateBrowserEndpoint(endpoint: Endpoint): Endpoint | null {
  const transport = endpoint.transport as BrowserTransport;
  if (transport !== "relay" && transport !== "discord") return null;
  if (!endpoint.room_id || !endpoint.host_public_key) return null;
  if (hex(sha256(b64d(endpoint.host_public_key))) !== endpoint.security.toLowerCase()) {
    throw new Error("Host identity fingerprint does not match");
  }
  const route = new URL(endpoint.endpoint);
  if (transport === "relay") {
    if (route.protocol !== "wss:") throw new Error("Invalid hosted relay route");
  } else {
    const allowed = ["discord.com", "www.discord.com", "ptb.discord.com", "canary.discord.com", "discordapp.com", "www.discordapp.com"];
    if (route.protocol !== "https:" || !allowed.includes(route.hostname)) throw new Error("Invalid Discord route");
  }
  return endpoint;
}

function parseInvite(uri: string, allowExpired = false): { endpoints: Endpoint[]; expires_at: number; guild_name: string } {
  if (uri.length > 16384) throw new Error("Pairing invitation is too large");
  const url = new URL(uri);
  if (url.protocol !== "djgoo:" || url.hostname !== "pair") throw new Error("Invalid DjGoo invitation");
  const payload = JSON.parse(dec.decode(b64d(url.searchParams.get("d") || "")));
  if (payload.protocol !== 2 || (!allowExpired && Number(payload.expires_at) <= Date.now() / 1000)) throw new Error("This pairing invitation has expired");
  const raw = Array.isArray(payload.endpoints) ? payload.endpoints : [];
  const endpoints = raw
    .map((item: Endpoint) => validateBrowserEndpoint(item))
    .filter((item: Endpoint | null): item is Endpoint => Boolean(item))
    .sort((a, b) => (a.transport === "relay" ? 0 : 1) - (b.transport === "relay" ? 0 : 1));
  if (!endpoints.length) throw new Error("This invitation has no browser-compatible route");
  return { endpoints, expires_at: Number(payload.expires_at), guild_name: String(payload.guild_name || "") };
}

function routesFromCredential(credential: WebCredential): WebRoute[] {
  const routes: WebRoute[] = [];
  for (const route of credential.routes || []) {
    if ((route.transport === "relay" || route.transport === "discord") && route.endpoint) routes.push(route);
  }
  if (credential.relay_url) routes.push({ transport: "relay", endpoint: credential.relay_url });
  if (credential.webhook_url) routes.push({ transport: "discord", endpoint: credential.webhook_url });
  const seen = new Set<string>();
  return routes.filter(route => {
    const key = `${route.transport}:${route.endpoint}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function remoteTransportKind(credential: WebCredential | null): BrowserTransport | null {
  if (!credential) return null;
  if (credential.transport === "relay" || credential.transport === "discord") return credential.transport;
  return routesFromCredential(credential)[0]?.transport || null;
}

export function inviteMatchesCredential(uri: string, credential: WebCredential): boolean {
  try {
    const { endpoints } = parseInvite(uri, true);
    return endpoints.some(endpoint =>
      endpoint.room_id === credential.room_id
      && endpoint.host_public_key === credential.host_public_key
    );
  } catch {
    return false;
  }
}

export function credentialWithInviteRoutes(uri: string, credential: WebCredential): WebCredential {
  try {
    const { endpoints } = parseInvite(uri, true);
    if (!endpoints.some(endpoint => endpoint.room_id === credential.room_id && endpoint.host_public_key === credential.host_public_key)) return credential;
    const routes = endpoints.map(endpoint => ({ transport: endpoint.transport as BrowserTransport, endpoint: endpoint.endpoint }));
    const preferred = routes[0];
    return {
      ...credential,
      transport: preferred?.transport || credential.transport,
      routes,
      relay_url: routes.find(route => route.transport === "relay")?.endpoint || credential.relay_url,
      webhook_url: routes.find(route => route.transport === "discord")?.endpoint || credential.webhook_url,
    };
  } catch {
    return credential;
  }
}

function prepareExchange(roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>): ExchangeContext {
  const requestId = crypto.randomUUID();
  const secret = x25519.utils.randomSecretKey();
  const clientPublic = x25519.getPublicKey(secret);
  const shared = x25519.getSharedSecret(secret, b64d(hostPublicKey));
  const salt = sha256(enc.encode(roomId));
  const key = hkdf(sha256, shared, salt, enc.encode(`djgoo-relay-v1:${requestId}:request`), 32);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const aad = enc.encode(`djgoo-relay-v1|${roomId}|${requestId}|request`);
  const ciphertext = chacha20poly1305(key, nonce, aad).encrypt(enc.encode(JSON.stringify({ action, payload })));
  return {
    requestId,
    secret,
    salt,
    roomId,
    envelope: { protocol: 1, room_id: roomId, request_id: requestId, client_public_key: b64e(clientPublic), nonce: b64e(nonce), ciphertext: b64e(ciphertext) },
  };
}

async function decodeEncryptedResult(encrypted: Record<string, any>, context: ExchangeContext) {
  if (encrypted.request_id !== context.requestId || encrypted.room_id !== context.roomId) throw new Error("Host response identity changed");
  const responseShared = x25519.getSharedSecret(context.secret, b64d(encrypted.host_ephemeral_public_key));
  const responseKey = hkdf(sha256, responseShared, context.salt, enc.encode(`djgoo-relay-v1:${context.requestId}:response`), 32);
  const responseAad = enc.encode(`djgoo-relay-v1|${context.roomId}|${context.requestId}|response`);
  let plain = chacha20poly1305(responseKey, b64d(encrypted.nonce), responseAad).decrypt(b64d(encrypted.ciphertext));
  if (encrypted.encoding === "gzip-json") {
    const stream = new Blob([plain as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
    plain = new Uint8Array(await new Response(stream).arrayBuffer());
  }
  const result = JSON.parse(dec.decode(plain));
  if (!result.ok) throw new Error(String(result.error || "DjGoo Host rejected the request"));
  return result.result;
}

async function exchangeDiscord(routeUrl: string, roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>) {
  const context = prepareExchange(roomId, hostPublicKey, action, payload);
  const content = REQUEST + b64e(enc.encode(JSON.stringify(context.envelope)));
  if (content.length > MAX_CONTENT) throw new Error("Encrypted request is too large");
  const created = await createDiscordMessage(
    routeUrl,
    JSON.stringify({ content, flags: 4096, allowed_mentions: { parse: [] } }),
  );
  if (!created?.ok) throw new Error(`Discord is busy (${created?.status || "offline"}). DjGoo will retry another secure route when available.`);
  const messageId = String((await discordJson(created, "opening the secure connection")).id || "");
  if (!messageId) throw new Error("Discord did not return a secure message ID. Try the newest DjGoo link.");
  const messageUrl = `${routeUrl}/messages/${messageId}`;
  try {
    const deadline = Date.now() + 25000;
    let delay = 400;
    while (Date.now() < deadline) {
      const response = await pollDiscordMessage(messageUrl);
      if (!response) { await new Promise(r => setTimeout(r, delay = Math.min(delay * 2, 4000))); continue; }
      if (response.status === 429) { await new Promise(r => setTimeout(r, delay = Math.min(delay * 2, 4000))); continue; }
      if (response.ok) {
        const message = await discordJson(response, "waiting for DjGoo Host");
        let responseContent = String(message.content || "");
        if (responseContent.startsWith(RESPONSE_ATTACHMENT)) {
          const attachmentUrl = String(message.attachments?.[0]?.url || "");
          if (attachmentUrl) responseContent = await fetch(attachmentUrl, { cache: "no-store" }).then(item => item.text());
        }
        if (responseContent.startsWith(RESPONSE)) {
          const encrypted = JSON.parse(dec.decode(b64d(responseContent.slice(RESPONSE.length))));
          return await decodeEncryptedResult(encrypted, context);
        }
      }
      await new Promise(r => setTimeout(r, delay));
    }
    throw new Error("DjGoo could not retrieve the Host response from Discord.");
  } finally {
    await fetch(messageUrl, { method: "DELETE" }).catch(() => undefined);
  }
}

function relayClientUrl(routeUrl: string, roomId: string): string {
  const url = new URL(routeUrl);
  if (url.protocol !== "wss:") throw new Error("DjGoo hosted relay must use wss://");
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/v1/client/${encodeURIComponent(roomId)}`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

async function exchangeRelay(routeUrl: string, roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>) {
  const context = prepareExchange(roomId, hostPublicKey, action, payload);
  return await new Promise<any>((resolve, reject) => {
    const socket = new WebSocket(relayClientUrl(routeUrl, roomId));
    let settled = false;
    const finish = (error?: Error, result?: any) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      try { socket.close(); } catch { /* no-op */ }
      if (error) reject(error);
      else resolve(result);
    };
    const timer = window.setTimeout(() => finish(new Error("DjGoo hosted relay timed out")), 20000);
    socket.onopen = () => socket.send(JSON.stringify({ type: "relay_request", envelope: context.envelope }));
    socket.onerror = () => finish(new Error("DjGoo hosted relay connection failed"));
    socket.onclose = () => {
      if (!settled) finish(new Error("DjGoo hosted relay closed before the Host responded"));
    };
    socket.onmessage = event => {
      void (async () => {
        try {
          const response = JSON.parse(String(event.data || "{}"));
          if (response.type === "error") throw new Error(`DjGoo hosted relay: ${String(response.code || "unknown error")}`);
          if (response.type !== "relay_response" || !response.envelope) return;
          finish(undefined, await decodeEncryptedResult(response.envelope, context));
        } catch (error) {
          finish(error instanceof Error ? error : new Error(String(error)));
        }
      })();
    };
  });
}

async function exchangeRoute(route: WebRoute, roomId: string, hostPublicKey: string, action: string, payload: Record<string, unknown>) {
  if (route.transport === "relay") return exchangeRelay(route.endpoint, roomId, hostPublicKey, action, payload);
  return exchangeDiscord(route.endpoint, roomId, hostPublicKey, action, payload);
}

async function exchangeCredential(credential: WebCredential, action: string, payload: Record<string, unknown>) {
  const routes = routesFromCredential(credential);
  if (!routes.length) throw new Error("This DjGoo web session has no usable secure route. Run /djgoo web again.");
  let lastError: Error | null = null;
  for (const route of routes) {
    try {
      return await exchangeRoute(route, credential.room_id, credential.host_public_key, action, payload);
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }
  throw lastError || new Error("DjGoo could not reach the Host");
}

export async function pairWeb(invite: string, deviceName: string): Promise<{ credential: WebCredential; guildName: string }> {
  const { endpoints, guild_name } = parseInvite(invite);
  let lastError: Error | null = null;
  for (const endpoint of endpoints) {
    try {
      const route = { transport: endpoint.transport as BrowserTransport, endpoint: endpoint.endpoint };
      const result = await exchangeRoute(route, endpoint.room_id, endpoint.host_public_key, "pair", { code: endpoint.code, device_name: deviceName });
      if (result.device_type !== "web") throw new Error("Host returned the wrong device type");
      const routes = endpoints
        .filter(item => item.room_id === endpoint.room_id && item.host_public_key === endpoint.host_public_key)
        .map(item => ({ transport: item.transport as BrowserTransport, endpoint: item.endpoint }));
      return {
        credential: {
          transport: route.transport,
          routes,
          webhook_url: routes.find(item => item.transport === "discord")?.endpoint,
          relay_url: routes.find(item => item.transport === "relay")?.endpoint,
          room_id: endpoint.room_id,
          host_public_key: endpoint.host_public_key,
          host_fingerprint: endpoint.security,
          ...result,
        },
        guildName: guild_name,
      };
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }
  throw lastError || new Error("DjGoo could not pair through any secure route");
}

export const remoteState = (c: WebCredential) => exchangeCredential(c, "web/state", { device_token: c.device_token, device_id: c.device_id, guild_id: c.guild_id });
export const remoteCommand = (c: WebCredential, intent: string, values: Record<string, unknown> = {}) => exchangeCredential(c, "command", { ...values, intent, command_id: crypto.randomUUID(), created_at: Date.now() / 1000, confidence: 1, device_token: c.device_token, device_id: c.device_id, guild_id: c.guild_id });
