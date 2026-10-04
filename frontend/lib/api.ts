// Peeker API client: types mirror backend/app/schemas.py.

/**
 * Where the dashboard's data actually lives. NEXT_PUBLIC_API_URL overrides the
 * default same-origin /backend proxy when the backend sits somewhere else.
 *
 * Defaulting to the relative "/backend" is deliberate, not lazy: the dashboard
 * session cookie is scoped to the app's host, and credentials: "include" cannot
 * carry it to a *different* host even when the port matches. The rewrite in
 * next.config.mjs forwards /backend/* to the FastAPI server, so the browser sees
 * one origin and the cookie always arrives. An absolute override re-opens the
 * host-mismatch hole only if the same cookie is visible on that host.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/backend";

/**
 * Human-readable backend address for status and error lines (never a request).
 * Relative API_URL means "same origin, via the /backend proxy", so name the proxy
 * path itself; anything in BACKEND_* only matters when an absolute
 * NEXT_PUBLIC_API_URL points past the proxy.
 */
export function backendLabel(): string {
  if (API_URL.startsWith("/")) return `this app at ${API_URL}`;
  return API_URL;
}

export interface Stats {
  businesses: number;
  queued: number;
  scraping: number;
  idle: number;
  backoff: number;
  parked: number;
  reviews: number;
  open_alerts: number;
}

export interface Business {
  id: number;
  name: string;
  maps_url: string;
  kind: "own" | "competitor";
  avg_rating: number | null; // latest snapshot; null until first scrape
  review_count: number | null;
  status: string;
  address: string | null;
  phone: string | null;
  website: string | null;
  category: string | null;
  opening_hours: string | null;
  next_due_at: string | null;
  /** Latest rating snapshot's taken_at — i.e. when this listing was last scraped. */
  last_scraped_at: string | null;
  consecutive_blocks: number;
  parked_until: string | null;
  created_at: string;
  updated_at: string;
}

export interface Alert {
  id: number;
  business_id: number;
  kind: string;
  message: string;
  urgent: boolean;
  created_at: string;
  seen: boolean;
}

export interface Review {
  id: number;
  business_id: number;
  business_name: string;
  google_review_id: string;
  author: string;
  rating: number;
  text: string;
  review_time: string | null;
  first_seen_at: string;
}

/** POST body for a new listing. There is no `enqueue` flag: the backend defaults
 *  it to true, so adding a business always queues its first scrape. */
export interface BusinessCreate {
  name: string;
  maps_url: string;
  kind: "own" | "competitor";
}

/** PATCH body: only the fields that changed are sent (the endpoint rejects an empty patch). */
export interface BusinessUpdate {
  name?: string;
  maps_url?: string;
}

export interface Performance {
  id: number;
  business_id: number;
  source_name: string; // CSV location/business name of this upload
  period: string;
  period_date: string | null;
  search_mobile: number;
  search_desktop: number;
  maps_mobile: number;
  maps_desktop: number;
  calls: number;
  directions: number;
  website_clicks: number;
  imported_at: string;
}

export interface PerformanceUpload {
  business_id: number | null; // null when no single business matched (split per location)
  business_name: string;
  matched: boolean; // false → nothing attached; rows stay pending until that business exists
  imported: number;
  periods: string[];
  attached_locations: string[]; // CSV locations that landed on a tracked business
  pending_locations: string[]; // CSV locations stored pending (business not tracked yet)
}

/** Reviews the polling views ask for. The backend caps this at REVIEW_LIMIT_MAX (2000) rows per call. */
export const REVIEW_PAGE_SIZE = 200;

export interface AlertsSeenOut {
  updated: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    // The backend verifies the dashboard's peeker_session cookie (backend/app/auth.py),
    // and fetch defaults to credentials: "same-origin", which would silently withhold
    // it. Through the default same-origin "/backend" proxy this is belt-and-braces;
    // through an absolute NEXT_PUBLIC_API_URL it is the only thing carrying the cookie.
    credentials: "include",
    ...init,
  });
  return unwrapJson<T>(res);
}

/**
 * Shared error handling for the non-`request()` paths (multipart upload, binary download):
 * FastAPI errors come as `{detail: ...}`; a non-JSON body falls back to the status text.
 * Must stay byte-for-byte identical to what `request()` does, so an upload fails the same
 * way a JSON body does.
 */
async function unwrapJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  stats: () => request<Stats>("/api/stats"),
  businesses: () => request<Business[]>("/api/businesses"),
  createBusiness: (payload: BusinessCreate) =>
    request<Business>("/api/businesses", { method: "POST", body: JSON.stringify(payload) }),
  updateBusiness: (id: number, payload: BusinessUpdate) =>
    request<Business>(`/api/businesses/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  enqueue: (id: number) => request<Business>(`/api/businesses/${id}/enqueue`, { method: "POST" }),
  enqueueAll: () => request<Business[]>("/api/enqueue-all", { method: "POST" }),
  deleteBusiness: (id: number) =>
    request<void>(`/api/businesses/${id}`, { method: "DELETE" }),
  reviews: (id: number, limit: number = REVIEW_PAGE_SIZE) =>
    request<Review[]>(`/api/businesses/${id}/reviews?limit=${limit}`),
  reviewsAll: (opts?: { businessId?: number; limit?: number }) => {
    const params = new URLSearchParams();
    params.set("limit", String(opts?.limit ?? REVIEW_PAGE_SIZE));
    if (opts?.businessId !== undefined) params.set("business_id", String(opts.businessId));
    return request<Review[]>(`/api/reviews?${params.toString()}`);
  },
  performance: (id: number) => request<Performance[]>(`/api/businesses/${id}/performance`),
  uploadPerformance: async (file: File, businessId?: number): Promise<PerformanceUpload> => {
    const form = new FormData();
    form.append("file", file);
    if (businessId !== undefined) form.append("business_id", String(businessId));
    // Do NOT set Content-Type here. The browser must add the multipart boundary.
    // credentials mirrors request() above: the upload route verifies the session cookie.
    // Note it goes to the same `${API_URL}` base, so it shares the proxy too.
    const res = await fetch(`${API_URL}/api/performance/upload`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    return unwrapJson<PerformanceUpload>(res);
  },
  /** Download a full SQLite backup (Kwerry /api/backup). Streams the .db file. */
  downloadBackup: async (): Promise<void> => {
    const res = await fetch(`${API_URL}/api/backup`, { credentials: "include" });
    const blob = await unwrapJson<Blob>(res);
    const name =
      res.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] ??
      `peeker-backup-${new Date().toISOString().slice(0, 19).replace(/[:.]/g, "-")}.db`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
  /** Restore the database from an uploaded .db file (Kwerry /api/backup/restore). */
  restoreBackup: async (file: File): Promise<{ message: string }> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/api/backup/restore`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    return unwrapJson<{ message: string }>(res);
  },
  alerts: () => request<Alert[]>("/api/alerts"),
  markAlertSeen: (id: number) =>
    request<Alert>(`/api/alerts/${id}/seen`, { method: "POST" }),
  markAllAlertsSeen: () =>
    request<AlertsSeenOut>("/api/alerts/seen-all", { method: "POST" }),
};

/** Shown wherever a value the crawler has not collected (or never will) belongs. */
export const EMPTY_VALUE = "n/a";

/**
 * Backend datetimes are naive UTC; make sure JS parses them as UTC.
 * Returns null when the string is empty or unparseable.
 */
export function parseIsoDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasTz = /Z|[+-]\d{2}:\d{2}$/.test(iso);
  const d = new Date(hasTz ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return EMPTY_VALUE;
  const d = parseIsoDate(iso);
  if (!d) return iso;
  return d.toLocaleString();
}

/** Same UTC handling as fmtDate, but local date + time without the seconds (upload stamps). */
export function fmtStamp(iso: string | null | undefined): string {
  if (!iso) return EMPTY_VALUE;
  const d = parseIsoDate(iso);
  if (!d) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compact relative time for the sync label (“just now”, “12s ago”, “3m ago”). */
export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return EMPTY_VALUE;
  const d = parseIsoDate(iso);
  if (!d) return iso;
  const secs = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return fmtStamp(iso);
}

/** True for an absolute http(s) URL. Shared by the add form and the edit modal so both
 *  accept exactly the same links. */
export function isHttpUrl(value: string): boolean {
  try {
    return /^https?:$/.test(new URL(value.trim()).protocol);
  } catch {
    return false;
  }
}
