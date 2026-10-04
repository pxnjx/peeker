"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ThemeToggle from "@/components/ThemeToggle";
import BrandPin from "@/components/BrandPin";
import {
  AlertsIcon,
  AnalyzeIcon,
  BusinessesIcon,
  CloseIcon,
  ListIcon,
  OverviewIcon,
  PerformanceIcon,
  RefreshIcon,
  ReviewsIcon,
  SettingsIcon,
  SignOutIcon,
  UserIcon,
} from "@/components/icons";
import { fmtAgo, fmtStamp } from "@/lib/api";
import {
  DashboardContext,
  useDashboardData,
} from "@/lib/useDashboardData";

// Re-exported so pages keep importing the nav list from AppShell.
export { REFRESH_OPTIONS } from "@/lib/useDashboardData";
export type { RefreshInterval } from "@/lib/useDashboardData";
export { useDashboard } from "@/lib/useDashboardData";

/**
 * Kwerry side nav, one entry per dashboard route. `hint` feeds the sticky
 * topbar subtitle; `Icon` renders the Phosphor glyph left of the label.
 */

export const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", hint: "Crawler status, totals & open alerts", Icon: OverviewIcon },
  { href: "/dashboard/businesses", label: "Businesses", hint: "Add, edit & rescan listings", Icon: BusinessesIcon },
  { href: "/dashboard/analyze", label: "Analyze", hint: "Ratings, comment coverage & own vs competitor standing", Icon: AnalyzeIcon },
  { href: "/dashboard/performance", label: "Performance", hint: "Google Business Profile CSV per location", Icon: PerformanceIcon },
  { href: "/dashboard/reviews", label: "Reviews", hint: "Stored Google Maps reviews, newest first", Icon: ReviewsIcon },
  { href: "/dashboard/alerts", label: "Alerts", hint: "Rating drops and review bursts", Icon: AlertsIcon },
  { href: "/dashboard/settings", label: "Settings", hint: "Password & database backup / restore", Icon: SettingsIcon },
] as const;

export default function AppShell({ children }: { children: React.ReactNode }) {
  const data = useDashboardData();
  const [dismissedError, setDismissedError] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [popOpen, setPopOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  // Mobile nav drawer, shown under 900px in place of the rail. Closed by default
  // and toggled by the burger in the topbar; the desktop markup below is
  // untouched because .mobile-nav is display:none above the breakpoint.
  const [navOpen, setNavOpen] = useState(false);
  // The menu and the sign-out confirm are both portalled to <body> (see the
  // render), so they need their own refs: `triggerRef` anchors them, and the two
  // panel refs keep an outside-click from closing a panel the moment you reach
  // into it. `anchorPos` is the trigger's viewport rect, measured on open.
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  // The drawer carries a second profile trigger, and either one can open the
  // shared menu — so the panel anchors to whichever fired, tracked here.
  const drawerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const activeTriggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const confirmRef = useRef<HTMLDivElement | null>(null);
  // The click that opens a panel must not also close it. React flushes a click's
  // state update before the document listener runs, so by the time onDoc fires
  // the menu it came from has already unmounted and its ref reads null — which
  // makes that click look "outside". This flag swallows exactly that one click.
  const skipDocRef = useRef(false);
  const [anchorPos, setAnchorPos] = useState<{ top: number; left: number; width?: number } | null>(null);
  const pathname = usePathname();
  const router = useRouter();

  /** Who is signed in? Powers the Kwerry-style user trigger in the side foot. */
  useEffect(() => {
    let live = true;
    fetch("/api/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (live) setUsername(typeof d?.user?.username === "string" ? d.user.username : null);
      })
      .catch(() => {
        if (live) setUsername(null);
      });
    return () => {
      live = false;
    };
  }, []);

  /** Open the profile menu beside the trigger that fired, in viewport
   *  coordinates. `el` is the trigger's element: the rail row on desktop, the
   *  drawer's foot row on mobile. */
  function toggleMenu(el: HTMLButtonElement | null) {
    if (popOpen) {
      setPopOpen(false);
      return;
    }
    activeTriggerRef.current = el;
    const r = el?.getBoundingClientRect();
    if (r) setAnchorPos({ top: r.top, left: r.left, width: r.width });
    setPopOpen(true);
  }

  /** Sign out: close the menu and raise the confirm card directly above the
   *  trigger, matching its width so the card reads as attached to the profile row
   *  rather than a panel floating over the page beside the rail. */
  function askSignOut() {
    skipDocRef.current = true;
    const r = activeTriggerRef.current?.getBoundingClientRect();
    if (r) setAnchorPos({ top: r.top, left: r.left, width: r.width });
    setPopOpen(false);
    setLogoutOpen(true);
  }

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (skipDocRef.current) {
        skipDocRef.current = false;
        return;
      }
      const t = e.target as Node;
      // Both panels live on <body>, so test every anchor before treating a click
      // as outside — otherwise clicking the trigger would close what it opened.
      // The drawer has its own profile trigger, so that row counts too.
      if (
        triggerRef.current?.contains(t) ||
        drawerTriggerRef.current?.contains(t) ||
        menuRef.current?.contains(t) ||
        confirmRef.current?.contains(t)
      ) {
        return;
      }
      setPopOpen(false);
      setLogoutOpen(false);
    };
    document.addEventListener("click", onDoc);
    return () => document.removeEventListener("click", onDoc);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPopOpen(false);
        setLogoutOpen(false);
        // Escape closes the drawer too, and takes priority: it is the outermost
        // layer on mobile, so a second Escape drills into the panel under it.
        if (navOpen) {
          setNavOpen(false);
          return;
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navOpen]);

  /* The drawer is a mobile-only layer, but the viewport can be resized or
     rotated while it is open. Leaving it parked open over a desktop-width rail
     would strand the burger's state, so any navigation — or the breakpoint
     itself being crossed — dismisses it. */
  useEffect(() => {
    setNavOpen(false);
    setPopOpen(false);
  }, [pathname]);

  /* Desktop keeps the rail, so the drawer has nothing to do above 900px. Mirror
     the CSS breakpoint here and dismiss the drawer when it stops matching, so a
     rotate or a resize never strands it open over the desktop layout. */
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 901px)");
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) setNavOpen(false);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  /** Clear the session cookie, then hand the browser back to the login screen. */
  async function signOut() {
    try {
      await fetch("/api/logout", { method: "POST" });
    } finally {
      router.replace("/login");
    }
  }

  const { businesses, openAlerts, refreshing, lastSync, error } = data;
  const current = NAV_ITEMS.find((n) => n.href === pathname) ?? NAV_ITEMS[0];

  return (
    <DashboardContext.Provider value={data}>
      <div className="app-shell">
        {/* Mobile nav drawer. Both layers are display:none above 900px (see the
            z-index note in dashboard.css), so the desktop rail below is the only
            nav a wide viewport ever sees. The drawer stays mounted while closed
            so its slide-out can play. */}
        {navOpen && (
          <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
        )}
        <nav
          id="mobile-nav"
          className={`mobile-nav${navOpen ? " open" : ""}`}
          aria-label="Primary mobile"
        >
          <div className="mobile-nav-head">
            <span className="brand">
              <span className="brand-mark" aria-hidden="true">
                <BrandPin size={28} />
              </span>
              <span className="brand-text">
                <strong>Peeker</strong>
                <span>Google Maps reviews &amp; competitor monitoring</span>
              </span>
            </span>
            <button
              className="mobile-nav-close"
              type="button"
              aria-label="Close navigation menu"
              onClick={() => setNavOpen(false)}
            >
              <CloseIcon />
            </button>
          </div>

          <div className="mobile-nav-scroll">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`side-link mobile-nav-link${
                  pathname === item.href ? " active" : ""
                }`}
                aria-current={pathname === item.href ? "page" : undefined}
              >
                <item.Icon />
                <span className="side-label">{item.label}</span>
                {item.href === "/dashboard/businesses" && businesses.length > 0 && (
                  <span className="pill">{businesses.length}</span>
                )}
                {item.href === "/dashboard/alerts" && openAlerts > 0 && (
                  <span className="pill warn">{openAlerts}</span>
                )}
              </Link>
            ))}
          </div>

          {/* Account + studio credit pinned to the foot, mirroring the rail's
              bottom block so both navs read as the same thing. */}
          <div className="mobile-nav-foot">
            <button
              ref={drawerTriggerRef}
              className="side-link mobile-user-trigger"
              type="button"
              onClick={() => toggleMenu(drawerTriggerRef.current)}
              aria-haspopup="menu"
              aria-expanded={popOpen}
            >
              <UserIcon />
              <span className="user-label">{username ?? "Profile"}</span>
            </button>
            <div className="mobile-nav-sign">
              <div className="side-sign">
                <a
                  className="side-sign-name"
                  href="https://scrambledhead.pxnjx.com/"
                  target="_blank"
                  rel="noopener"
                >
                  scrambled_head.studio
                </a>
                <span className="side-sign-meta">(c) 2026 · All scribbles reserved.</span>
              </div>
            </div>
          </div>
        </nav>

        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              <BrandPin size={28} />
            </span>
            <div className="brand-text">
              <strong>Peeker</strong>
              <span title="Google Maps reviews & competitor monitoring">
                Google Maps reviews &amp; competitor monitoring
              </span>
            </div>
          </div>
          <nav className="side-nav" aria-label="Primary">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`side-link${pathname === item.href ? " active" : ""}`}
                aria-current={pathname === item.href ? "page" : undefined}
              >
                <item.Icon />
                <span className="side-label">{item.label}</span>
                {item.href === "/dashboard/businesses" && businesses.length > 0 && (
                  <span className="pill">{businesses.length}</span>
                )}
                {item.href === "/dashboard/alerts" && openAlerts > 0 && (
                  <span className="pill warn">{openAlerts}</span>
                )}
              </Link>
            ))}
          </nav>
          <div className="side-bottom">
            {/* profile row — sits above the footer strip */}
            <div className="side-user-menu">
              <button
                ref={triggerRef}
                className="side-link side-btn user-trigger"
                type="button"
                onClick={() => toggleMenu(triggerRef.current)}
                aria-haspopup="menu"
                aria-expanded={popOpen}
              >
                <UserIcon />
                <span className="user-label">{username ?? "Profile"}</span>
              </button>
            </div>

            <div className="side-foot">
              <div className="side-sign">
                <a
                  className="side-sign-name"
                  href="https://scrambledhead.pxnjx.com/"
                  target="_blank"
                  rel="noopener"
                >
                  scrambled_head.studio
                </a>
                <span className="side-sign-meta">(c) 2026 · All scribbles reserved.</span>
              </div>
            </div>
          </div>
        </aside>

        {/* The profile menu is portalled to <body>: as a descendant of .sidebar
            it was clipped by that rail's `overflow-x: hidden`, which left a 200px
            menu with only 9px visible and the item unclickable. Fixed positioning
            from the trigger's rect escapes the clip and keeps the Kwerry look of a
            panel floating clear of the rail. */}
        {popOpen &&
          anchorPos &&
          createPortal(
            <div
              className="user-popover"
              ref={menuRef}
              role="menu"
              style={{
                top: anchorPos.top,
                left: anchorPos.left,
                width: anchorPos.width,
              }}
            >
              <div className="user-popover-head">
                <strong>{username ?? "…"}</strong>
              </div>
              <button
                className="user-popover-item"
                type="button"
                role="menuitem"
                onClick={askSignOut}
              >
                <SignOutIcon />
                Sign out
              </button>
            </div>,
            document.body,
          )}

        <div className="main-area">
          <div className="main-col">
            <header className="topbar">
              {/* Burger: the drawer's only trigger. display:none above 900px, so
                  the desktop topbar keeps its original layout untouched. */}
              <button
                className="topbar-burger"
                type="button"
                onClick={() => setNavOpen((v) => !v)}
                aria-label="Open navigation menu"
                aria-expanded={navOpen}
                aria-controls="mobile-nav"
              >
                <ListIcon />
              </button>
              <div className="topbar-heading">
                <span className="eyebrow">PEEKER</span>
                <h1 className="topbar-title">{current.label}</h1>
                <p className="topbar-sub">{current.hint}</p>
              </div>
              <div className="topbar-actions">
                {/* Sits immediately left of Refresh, on the same line. */}
                <span className="muted sync-label" title={lastSync ? fmtStamp(lastSync) : undefined}>
                  {refreshing ? "syncing…" : lastSync ? `synced ${fmtAgo(lastSync)}` : "connecting…"}
                </span>
                <button
                  className="ghost"
                  onClick={() => void data.refresh()}
                  disabled={refreshing}
                  aria-label="Refresh data"
                >
                  <RefreshIcon className={refreshing ? "spin" : undefined} />
                  {refreshing ? "Syncing…" : "Refresh"}
                </button>
              </div>
            </header>
            <main className="container">
              {error && error !== dismissedError && (
                <div className="error-banner" role="alert">
                  {error}
                  <button
                    type="button"
                    className="banner-dismiss"
                    onClick={() => setDismissedError(error)}
                    aria-label="Dismiss error"
                  >
                    <CloseIcon />
                  </button>
                </div>
              )}
              {children}
            </main>
          </div>
          {/* Shell corner control: pinned to the main area's top-right, outside
              the content column so it never collides with the topbar row. */}
          <ThemeToggle />
        </div>
      </div>

      {/* The confirm rises directly above the profile trigger, in the same place the
          menu appeared, instead of taking over the screen. It is portalled and
          fixed for the same clipping reason as the menu, and without a backdrop
          it is no longer a modal dialog — so it drops aria-modal and relies on
          outside-click / Escape, both handled above. */}
      {logoutOpen &&
        anchorPos &&
        createPortal(
          <div
            className="modal modal-sm signout-popover"
            ref={confirmRef}
            role="dialog"
            aria-labelledby="signout-title"
            style={{
              top: anchorPos.top,
              left: anchorPos.left,
              width: anchorPos.width,
            }}
          >
            <div className="modal-head">
              <h3 id="signout-title">Sign out?</h3>
              <button
                type="button"
                className="banner-dismiss"
                onClick={() => setLogoutOpen(false)}
                aria-label="Close sign out dialog"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="modal-body">
              <p className="muted" style={{ margin: 0 }}>
                You will need to sign in again to access the dashboard.
              </p>
            </div>
            <div className="modal-foot">
              <button type="button" className="ghost" onClick={() => setLogoutOpen(false)}>
                Cancel
              </button>
              {/* warning, not primary: the confirm now carries the
                  session-ending hue, glyph included via currentColor. */}
              <button type="button" className="warning" onClick={() => void signOut()}>
                <SignOutIcon />
                Sign out
              </button>
            </div>
          </div>,
          document.body,
        )}
    </DashboardContext.Provider>
  );
}
