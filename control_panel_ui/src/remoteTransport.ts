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

type Endpoint = { transport: string; endpoint: string; security: string; code: string; room_id: string; host_public_key: string };
export type WebCredential = { webhook_url: string; room_id: string; host_public_key: string; host_fingerprint: string; device_id: string; device_token: string; discord_user_id: string; guild_id: string; device_type: string; capabilities: string[] };

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

function parseInvite(uri: string, allowExpired = false): { endpoint: Endpoint; expires_at: number; guild_name: string } {
  if (uri.length > 16384) throw new Error("Pairing invitation is too large");
  const url = new URL(uri);
  if (url.protocol !== "djgoo:" || url.hostname !== "pair") throw new Error("Invalid DjGoo invitation");
  const payload = JSON.parse(dec.decode(b64d(url.searchParams.get("d") || "")));
  if (payload.protocol !== 2 || (!allowExpired && Number(payload.expires_at) <= Date.now() / 1000)) throw new Error("This pairing invitation has expired");
  const endpoint = payload.endpoints?.find((item: Endpoint) => item.transport === "discord");
  if (!endpoint) throw new Error("This invitation has no browser-compatible route");
  const hook = new URL(endpoint.endpoint);
  if (hook.protocol !== "https:" || !["discord.com", "www.discord.com", "ptb.discord.com", "canary.discord.com"].includes(hook.hostname)) throw new Error("Invalid Discord route");
  if (hex(sha256(b64d(endpoint.host_public_key))) !== endpoint.security.toLowerCase()) throw new Error("Host identity fingerprint does not match");
  return { endpoint, expires_at: payload.expires_at, guild_name: String(payload.guild_name || "") };
}

export function inviteMatchesCredential(uri: string, credential: WebCredential): boolean {
  try {
    const { endpoint } = parseInvite(uri, true);
    return endpoint.endpoint === credential.webhook_url
      && endpoint.room_id === credential.room_id
      && endpoint.host_public_key === credential.host_public_key;
  } catch {
    return false;
  }
}

async function exchange(endpoint: Pick<WebCredential, "webhook_url" | "room_id" | "host_public_key">, action: string, payload: Record<string, unknown>) {
  const requestId = crypto.randomUUID();
  const secret = x25519.utils.randomSecretKey();
  const clientPublic = x25519.getPublicKey(secret);
  const shared = x25519.getSharedSecret(secret, b64d(endpoint.host_public_key));
  const salt = sha256(enc.encode(endpoint.room_id));
  const key = hkdf(sha256, shared, salt, enc.encode(`djgoo-relay-v1:${requestId}:request`), 32);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const aad = enc.encode(`djgoo-relay-v1|${endpoint.room_id}|${requestId}|request`);
  const ciphertext = chacha20poly1305(key, nonce, aad).encrypt(enc.encode(JSON.stringify({ action, payload })));
  const envelope = { protocol: 1, room_id: endpoint.room_id, request_id: requestId, client_public_key: b64e(clientPublic), nonce: b64e(nonce), ciphertext: b64e(ciphertext) };
  const content = REQUEST + b64e(enc.encode(JSON.stringify(envelope)));
  if (content.length > MAX_CONTENT) throw new Error("Encrypted request is too large");
  let created: Response | null = null;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    created = await fetch(endpoint.webhook_url + "?wait=true", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, flags: 4096, allowed_mentions: { parse: [] } }) });
    if (created.status !== 429) break;
    const limited = await created.clone().json().catch(() => ({}));
    const retrySeconds = Math.max(0.5, Math.min(15, Number(limited.retry_after || 1)));
    await new Promise(resolve => setTimeout(resolve, retrySeconds * 1000));
  }
  if (!created?.ok) throw new Error(`Discord is busy (${created?.status || "offline"}). DjGoo will retry when you tap Retry.`);
  const messageId = String((await discordJson(created, "opening the secure connection")).id || "");
  if (!messageId) throw new Error("Discord did not return a secure message ID. Try the newest DjGoo link.");
  const messageUrl = `${endpoint.webhook_url}/messages/${messageId}`;
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
          if (encrypted.request_id !== requestId || encrypted.room_id !== endpoint.room_id) throw new Error("Host response identity changed");
          const responseShared = x25519.getSharedSecret(secret, b64d(encrypted.host_ephemeral_public_key));
          const responseKey = hkdf(sha256, responseShared, salt, enc.encode(`djgoo-relay-v1:${requestId}:response`), 32);
          const responseAad = enc.encode(`djgoo-relay-v1|${endpoint.room_id}|${requestId}|response`);
          let plain = chacha20poly1305(responseKey, b64d(encrypted.nonce), responseAad).decrypt(b64d(encrypted.ciphertext));
          if (encrypted.encoding === "gzip-json") {
            const stream = new Blob([plain as BlobPart]).stream().pipeThrough(new DecompressionStream("gzip"));
            plain = new Uint8Array(await new Response(stream).arrayBuffer());
          }
          const result = JSON.parse(dec.decode(plain));
          if (!result.ok) throw new Error(String(result.error || "DjGoo Host rejected the request"));
          return result.result;
        }
      }
      await new Promise(r => setTimeout(r, delay));
    }
    throw new Error("DjGoo could not retrieve the Host response from Discord. Check the connection and tap Retry.");
  } finally { await fetch(messageUrl, { method: "DELETE" }).catch(() => undefined); }
}

export async function pairWeb(invite: string, deviceName: string): Promise<{ credential: WebCredential; guildName: string }> {
  const { endpoint, guild_name } = parseInvite(invite);
  const result = await exchange({ webhook_url: endpoint.endpoint, room_id: endpoint.room_id, host_public_key: endpoint.host_public_key }, "pair", { code: endpoint.code, device_name: deviceName });
  if (result.device_type !== "web") throw new Error("Host returned the wrong device type");
  return { credential: { webhook_url: endpoint.endpoint, room_id: endpoint.room_id, host_public_key: endpoint.host_public_key, host_fingerprint: endpoint.security, ...result }, guildName: guild_name };
}

export const remoteState = (c: WebCredential) => exchange(c, "web/state", { device_token: c.device_token, device_id: c.device_id, guild_id: c.guild_id });
export const remoteCommand = (c: WebCredential, intent: string, values: Record<string, unknown> = {}) => exchange(c, "command", { ...values, intent, command_id: crypto.randomUUID(), created_at: Date.now() / 1000, confidence: 1, device_token: c.device_token, device_id: c.device_id, guild_id: c.guild_id });
