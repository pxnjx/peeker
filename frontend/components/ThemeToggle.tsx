"use client";

import { useCallback, useEffect, useState } from "react";
import { MoonIcon, SunIcon } from "@/components/icons";

const THEME_STORAGE_KEY = "peeker.theme";

type Theme = "light" | "dark";

/** The inline script in app/layout.tsx already resolved the theme before paint. */
function currentTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export default function ThemeToggle() {
  // Starts null so the first client render matches the server render exactly; the real
  // theme is read from <html data-theme> after mount (set by the pre-paint script).
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    setTheme(currentTheme());
  }, []);

  const toggle = useCallback(() => {
    const next: Theme = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* private mode / quota: the switch still applies for this session */
    }
    setTheme(next);
  }, []);

  const dark = theme === "dark";
  const label = dark ? "Switch to light theme" : "Switch to dark theme";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      title={label}
      aria-label={label}
      aria-pressed={theme === null ? undefined : dark}
    >
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
