import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import BrandPin from "@/components/BrandPin";
import LoginForm from "@/components/LoginForm";
import { SESSION_COOKIE, safeNextPath, verifySession } from "@/lib/session";

/** A sign-in screen has no business in a search index. */
export const metadata: Metadata = {
  title: "Sign in",
  robots: { index: false, follow: false },
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  if (verifySession((await cookies()).get(SESSION_COOKIE)?.value)) redirect("/dashboard");

  const { next } = await searchParams;

  return (
    <main className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            <BrandPin size={20} />
          </span>
          <div className="brand-text">
            <strong>Peeker</strong>
            <span>Google Maps review monitoring</span>
          </div>
        </div>

        <LoginForm next={safeNextPath(next)} />

        <Link className="auth-back" href="/">
          ← Back to home
        </Link>
      </div>
    </main>
  );
}
