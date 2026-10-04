"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Kwerry-shaped auth card: stacked uppercase labels, full-width submit. Sign-in only —
 * accounts come from SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD on first boot, so there
 * is no signup path (see lib/users.ts). The server owns the truth and sets the cookie.
 */
export default function LoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** One-time first-run notice from the server: the generated admin password. */
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = (await response.json().catch(() => ({}))) as {
        detail?: string;
        notice?: string | null;
      };
      if (!response.ok) {
        setError(body.detail ?? `Request failed (${response.status}).`);
        return;
      }
      // A fresh install that generated its own password reports it here. Show it rather
      // than redirecting into a signed-out loop, or the operator can never get in.
      if (body.notice) {
        setNotice(body.notice);
        setPassword("");
        return;
      }
      router.replace(next);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="auth-form" onSubmit={submit} autoComplete="on">
        <h1>Sign in</h1>
        <p className="auth-sub">Use your local Peeker account.</p>

        <label htmlFor="auth-user">Username</label>
        <input
          id="auth-user"
          name="username"
          type="text"
          autoComplete="username"
          required
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />

        <label htmlFor="auth-pass">Password</label>
        <input
          id="auth-pass"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <button type="submit" disabled={busy || username.trim().length === 0 || password.length === 0}>
          {busy ? "Working…" : "Sign in"}
        </button>
      </form>

      {notice && (
        <div className="auth-notice-box" role="alert">
          <pre className="auth-notice">{notice}</pre>
          <button type="button" className="auth-notice-dismiss" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <div className="auth-error error" role="alert">
          {error}
        </div>
      )}
    </>
  );
}
