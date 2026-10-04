import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE, createSession, sessionSubject } from "@/lib/session";
import { changePassword } from "@/lib/users";

/** Change the signed-in account's password. Re-issues the session cookie. */
export async function POST(request: Request) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const subject = sessionSubject(token);
  if (!subject) {
    return NextResponse.json({ detail: "Not signed in." }, { status: 401 });
  }

  let currentPassword = "";
  let newPassword = "";
  try {
    const body = (await request.json()) as {
      currentPassword?: unknown;
      newPassword?: unknown;
    };
    currentPassword = typeof body.currentPassword === "string" ? body.currentPassword : "";
    newPassword = typeof body.newPassword === "string" ? body.newPassword : "";
  } catch {
    return NextResponse.json({ detail: "Malformed request body." }, { status: 400 });
  }

  try {
    changePassword(subject.id, currentPassword, newPassword);
    const session = createSession({ id: subject.id, method: "password" });
    const response = NextResponse.json({ ok: true });
    if (session) {
      response.cookies.set(SESSION_COOKIE, session.value, {
        httpOnly: true,
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
        path: "/",
        maxAge: session.maxAge,
      });
    }
    return response;
  } catch (err) {
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : "Could not change password." },
      { status: 400 },
    );
  }
}
