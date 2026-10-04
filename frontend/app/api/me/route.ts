import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, sessionSubject } from "@/lib/session";

/** Who is signed in? Lets the sidebar render the Kwerry-style user trigger. */
export async function GET() {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const subject = sessionSubject(token);
  if (!subject) {
    return NextResponse.json({ user: null }, { status: 401 });
  }
  return NextResponse.json({ user: { username: subject.id } });
}
