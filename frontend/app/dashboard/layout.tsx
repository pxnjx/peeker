import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import AppShell from "@/components/AppShell";
import { SESSION_COOKIE, verifySession } from "@/lib/session";

/**
 * The gate. Every dashboard route renders inside this layout, so a request
 * without a valid session cookie never reaches a page: it is redirected to
 * /login with the path it wanted, and the login form sends it back there.
 */
export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!verifySession(token)) redirect("/login?next=/dashboard");

  return <AppShell>{children}</AppShell>;
}
