import { NextResponse } from "next/server";
import { SESSION_COOKIE, createSession, sessionConfigured } from "@/lib/session";
import { checkLoginRate, clearLoginFails, clientIp, recordLoginFail } from "@/lib/rate-limit";
import { checkPassword, ensureSeedAdmin, userCount } from "@/lib/users";

/**
 * Username + password sign-in. Fails closed (503) when cookie signing is
 * unconfigured so a misconfigured deploy is never an open dashboard.
 */
export async function POST(request: Request) {
  if (!sessionConfigured()) {
    return NextResponse.json(
      {
        detail:
          "Sign-in is disabled: set PEEKER_SESSION_SECRET in the server environment.",
      },
      { status: 503 },
    );
  }

  // First boot of a fresh install: create the admin account once.
  const seedNotice = ensureSeedAdmin();

  const ip = clientIp(request);
  const rate = checkLoginRate(ip);
  if (!rate.ok) {
    return NextResponse.json(
      { detail: `Too many failed attempts. Try again in ${rate.waitSec}s.` },
      { status: 429 },
    );
  }

  let username = "";
  let password = "";
  try {
    const body = (await request.json()) as { username?: unknown; password?: unknown };
    username = typeof body.username === "string" ? body.username : "";
    password = typeof body.password === "string" ? body.password : "";
  } catch {
    return NextResponse.json({ detail: "Malformed request body." }, { status: 400 });
  }

  if (userCount() === 0) {
    return NextResponse.json(
      { detail: "No accounts yet. Restart the server to create the first admin, or register." },
      { status: 503 },
    );
  }

  const user = checkPassword(username, password);
  if (!user) {
    recordLoginFail(ip);
    return NextResponse.json({ detail: "Invalid username or password." }, { status: 401 });
  }

  clearLoginFails(ip);
  const session = createSession({ id: user.username, method: "password" });
  if (!session) {
    return NextResponse.json({ detail: "Session signing key unavailable." }, { status: 503 });
  }

  const response = NextResponse.json({ ok: true, username: user.username, notice: seedNotice });
  response.cookies.set(SESSION_COOKIE, session.value, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: session.maxAge,
  });
  return response;
}
