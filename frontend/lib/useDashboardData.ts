"use client";

/**
 * Dashboard data layer: polling, optimistic mutations, and the shared
 * DashboardValue shape. AppShell owns the chrome; pages consume this via
 * useDashboard().
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Alert, Business, BusinessCreate, BusinessUpdate, Stats } from "@/lib/api";
import { api, backendLabel } from "@/lib/api";

/** ms; 0 = manual (no auto-refresh). */
export type RefreshInterval = 0 | 5000 | 10000 | 30000 | 60000;

export const REFRESH_OPTIONS: { value: RefreshInterval; label: string }[] = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 10000, label: "10s" },
  { value: 30000, label: "30s" },
  { value: 60000, label: "60s" },
];

const REFRESH_STORAGE_KEY = "peeker.refreshInterval";
export const DEFAULT_REFRESH: RefreshInterval = 5000;

function loadRefreshInterval(): RefreshInterval {
  if (typeof window === "undefined") return DEFAULT_REFRESH;
  try {
    const raw = window.localStorage.getItem(REFRESH_STORAGE_KEY);
    if (raw === null) return DEFAULT_REFRESH;
    const n = Number(raw);
    return (REFRESH_OPTIONS.find((o) => o.value === n)?.value ??
      DEFAULT_REFRESH) as RefreshInterval;
  } catch {
    return DEFAULT_REFRESH;
  }
}

export interface DashboardValue {
  stats: Stats | null;
  businesses: Business[];
  alerts: Alert[];
  error: string | null;
  busyId: number | null;
  lastSync: string | null;
  openAlerts: number;
  refreshing: boolean;
  /** A bulk "mark all seen" request is in flight. */
  alertsBusy: boolean;
  refreshMs: RefreshInterval | null;
  changeRefresh: (value: RefreshInterval) => void;
  refresh: () => Promise<void>;
  addBusiness: (payload: BusinessCreate) => Promise<void>;
  enqueueOne: (id: number) => Promise<void>;
  enqueueAll: () => Promise<void>;
  removeBusiness: (id: number) => Promise<void>;
  updateBusiness: (id: number, patch: BusinessUpdate) => Promise<void>;
  markSeen: (id: number) => Promise<void>;
  markAllSeen: () => Promise<void>;
}

export const DashboardContext = createContext<DashboardValue | null>(null);

export function useDashboard(): DashboardValue {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard must be used within <AppShell>");
  return ctx;
}

export function useDashboardData(): DashboardValue {
  const [stats, setStats] = useState<Stats | null>(null);
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [refreshMs, setRefreshMs] = useState<RefreshInterval | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [alertsBusy, setAlertsBusy] = useState(false);
  const requestId = useRef(0);

  // Hydrate from localStorage after mount to avoid SSR mismatch.
  useEffect(() => {
    setRefreshMs(loadRefreshInterval());
  }, []);

  const changeRefresh = useCallback((value: RefreshInterval) => {
    setRefreshMs(value);
    try {
      window.localStorage.setItem(REFRESH_STORAGE_KEY, String(value));
    } catch {
      /* private mode / quota: keep in-memory only */
    }
  }, []);

  const refresh = useCallback(async () => {
    // Polls overlap when the API is slower than the interval: only the newest response may
    // touch state, otherwise a late reply repaints the table with stale data.
    const reqId = ++requestId.current;
    setRefreshing(true);
    try {
      const [s, b, a] = await Promise.all([api.stats(), api.businesses(), api.alerts()]);
      if (reqId !== requestId.current) return;
      setStats(s);
      setBusinesses(b);
      setAlerts(a);
      setLastSync(new Date().toISOString());
      setError(null);
    } catch (err) {
      if (reqId !== requestId.current) return;
      setError(
        `Cannot reach backend (${backendLabel()}): ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      if (reqId === requestId.current) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    // Initial load always runs (also covers Manual mode).
    void refresh();
    if (!refreshMs || refreshMs <= 0) return;

    const t = setInterval(() => {
      // Skip polling while the tab is hidden; refresh immediately when it comes back.
      if (!document.hidden) void refresh();
    }, refreshMs);
    const onVisible = () => {
      if (!document.hidden) void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, refreshMs]);

  async function addBusiness(payload: BusinessCreate) {
    await api.createBusiness(payload);
    await refresh();
  }

  async function enqueueOne(id: number) {
    setBusyId(id);
    try {
      await api.enqueue(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function enqueueAll() {
    setBusyId(-1);
    try {
      await api.enqueueAll();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  /** Patch the listing's name and/or Maps link. The edit dialog sends only what changed. */
  async function updateBusiness(id: number, patch: BusinessUpdate) {
    setBusyId(id);
    try {
      await api.updateBusiness(id, patch);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err; // the dialog keeps the values so they can be corrected
    } finally {
      setBusyId(null);
    }
  }

  async function removeBusiness(id: number) {
    const b = businesses.find((x) => x.id === id);
    if (!window.confirm(`Delete ${b?.name ?? id} and all its data?`)) return;
    setBusyId(id);
    try {
      await api.deleteBusiness(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function markSeen(id: number) {
    try {
      await api.markAlertSeen(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function markAllSeen() {
    setAlertsBusy(true);
    try {
      await api.markAllAlertsSeen();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAlertsBusy(false);
    }
  }

  return {
    stats,
    businesses,
    alerts,
    error,
    busyId,
    lastSync,
    openAlerts: alerts.filter((a) => !a.seen).length,
    refreshing,
    alertsBusy,
    refreshMs,
    changeRefresh,
    refresh,
    addBusiness,
    enqueueOne,
    enqueueAll,
    removeBusiness,
    updateBusiness,
    markSeen,
    markAllSeen,
  };
}
