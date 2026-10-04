// Server-only session helpers for the dashboard gate.
//
// Kwerry-style local accounts: username + scrypt password exchanged for a
// signed, httpOnly cookie. The signature is an HMAC over a versioned payload,
// so nothing needs to be stored server-side and a forged cookie cannot outlive
// the TTL. The subject id is the username.

import { createHmac, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "peeker_session";

/** Fourteen days: a working self-hosted install should not bounce people daily. */
const TTL_MS = 1000 * 60 * 60 * 24 * 14;

export interface AuthSubject {
  id: string;
  method: "password";
}

const TOKEN_VERSION = "v1";

function encodeSubject(id: string): string {
  return Buffer.from(id, "utf8").toString("base64url");
}

function decodeSubject(part: string | undefined): string | null {
  if (!part) return null;
  try {
    return Buffer.from(part, "base64url").toString("utf8");
  } catch {
    return null;
  }
}

/** Signing key: dedicated secret if set, otherwise a generated per-process key. */
function secret(): string | null {
  const value = process.env.PEEKER_SESSION_SECRET;
  return value && value.length > 0 ? value : null;
}

/** Whether cookie signing is possible. Fail closed when the secret is missing. */
export function sessionConfigured(): boolean {
  return secret() !== null;
}

function sign(payload: string, key: string): string {
  return createHmac("sha256", key).update(payload).digest("hex");
}

export function createSession(
  subject: AuthSubject,
  now = Date.now(),
): { value: string; maxAge: number } | null {
  const key = secret();
  if (!key) return null;
  const expiresAt = String(now + TTL_MS);
  const body = `${TOKEN_VERSION}.${subject.method}.${encodeSubject(subject.id)}.${expiresAt}`;
  return { value: `${body}.${sign(body, key)}`, maxAge: Math.floor(TTL_MS / 1000) };
}

export function sessionSubject(
  token: string | undefined | null,
  now = Date.now(),
): AuthSubject | null {
  const key = secret();
  if (!key || !token) return null;
  const parts = token.split(".");
  if (parts.length !== 5 || parts[0] !== TOKEN_VERSION) return null;
  const [, method, idPart, expiresAt, mac] = parts;
  if (method !== "password") return null;
  const id = decodeSubject(idPart);
  if (!id || !expiresAt || !mac) return null;
  const expected = sign(parts.slice(0, 4).join("."), key);
  const given = Buffer.from(mac, "hex");
  const want = Buffer.from(expected, "hex");
  if (given.length !== want.length || !timingSafeEqual(given, want)) return null;
  const expiry = Number(expiresAt);
  if (!Number.isFinite(expiry) || expiry <= now) return null;
  return { id, method: "password" };
}

export function verifySession(token: string | undefined | null, now = Date.now()): boolean {
  return sessionSubject(token, now) !== null;
}

/** Only same-origin, absolute paths are accepted as post-login destinations. */
export function safeNextPath(value: string | undefined | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/dashboard";
  return value;
}
