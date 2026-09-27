import { pageMeta } from "@/lib/metadata";
import Link from "next/link";

export const metadata = pageMeta("Page not found", "That page is not on the Swag Bot site.", "/404");

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60vh] w-full max-w-3xl flex-col justify-center px-4 py-24 md:px-6">
      <p className="kicker">404</p>
      <h1 className="h-display mt-3 text-5xl">This page is not here.</h1>
      <p className="mt-4 max-w-md text-muted">The address does not match a page on this site. The docs and the feature list are the two useful places to go next.</p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/" className="btn btn-accent">
          Home
        </Link>
        <Link href="/docs" className="btn btn-ghost">
          Docs
        </Link>
      </div>
    </div>
  );
}
