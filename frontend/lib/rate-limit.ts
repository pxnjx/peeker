/**
 * In-memory login rate limit, matching Kwerry: per-IP window with a hard cap
 * on failed attempts. Enough for a self-hosted install behind one operator.
 */

const WINDOW_MS = 15 * 60 * 1000;
const MAX_FAILS = 10;

const attempts = new Map<string, { count: number; resetAt: number }>();

export function checkLoginRate(ip: string): { ok: true } | { ok: false; waitSec: number } {
  const now = Date.now();
  const rec = attempts.get(ip);
  if (!rec || now > rec.resetAt) {
    attempts.set(ip, { count: 0, resetAt: now + WINDOW_MS });
    return { ok: true };
  }
  if (rec.count >= MAX_FAILS) {
    return { ok: false, waitSec: Math.ceil((rec.resetAt - now) / 1000) };
  }
  return { ok: true };
}

export function recordLoginFail(ip: string): void {
  const now = Date.now();
  const rec = attempts.get(ip) ?? { count: 0, resetAt: now + WINDOW_MS };
  rec.count += 1;
  attempts.set(ip, rec);
}

export function clearLoginFails(ip: string): void {
  attempts.delete(ip);
}

export function clientIp(request: Request): string {
  const fwd = request.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0]!.trim();
  return request.headers.get("x-real-ip") ?? "local";
}
