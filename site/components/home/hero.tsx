"use client";

import { InstallTabs } from "@/components/home/install-tabs";
import { Terminal } from "@/components/home/terminal";
import { GITHUB_URL, PRODUCT, RELEASES_URL, RELEASE_010_URL } from "@/lib/site";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useState } from "react";

const Canvas = dynamic(() => import("@/components/home/hero-canvas").then((mod) => mod.HeroCanvas), {
  ssr: false,
});

export function Hero() {
  const [showCanvas, setShowCanvas] = useState(false);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const narrow = window.matchMedia("(max-width: 47.99rem)").matches;
    const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } };
    const low =
      nav.connection?.saveData ||
      (nav.deviceMemory ?? 8) <= 2 ||
      (navigator.hardwareConcurrency ?? 8) <= 2;
    setShowCanvas(!reduced && !narrow && !low);
  }, []);

  return (
    <section className="relative overflow-hidden">
      {showCanvas ? (
        <div className="pointer-events-none absolute inset-0 opacity-80">
          <Canvas />
        </div>
      ) : (
        <div
          className="pointer-events-none absolute inset-0 opacity-70"
          style={{
            background:
              "radial-gradient(520px 280px at 78% 20%, var(--hero-glow), transparent 70%)",
          }}
          aria-hidden="true"
        />
      )}
      <div className="relative mx-auto grid w-full max-w-6xl items-center gap-12 px-4 pb-20 pt-14 md:px-6 md:pt-20 lg:grid-cols-[1.05fr_0.95fr]">
        <div>
          <p className="kicker">
            <a href={RELEASES_URL}>v{PRODUCT.versionLabel}</a>
            <span aria-hidden="true"> · </span>
            {PRODUCT.license}
            <span aria-hidden="true"> · </span>
            free
          </p>
          <h1 className="h-display mt-4 max-w-xl text-5xl sm:text-6xl lg:text-[4.4rem]">
            Done only when the evidence agrees.
          </h1>
          <p className="mt-6 max-w-xl text-lg text-muted">
            Swag Bot is a free, MIT-licensed general agent by {PRODUCT.author}. It plans the work, runs the step, and will not mark that step done unless a check cites real tool evidence.
          </p>
          <div id="install" className="mt-8 scroll-mt-28">
            <InstallTabs />
          </div>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link href="/docs/quickstart" className="btn btn-accent">
              Read the quickstart
            </Link>
            <a href={GITHUB_URL} className="btn btn-ghost">
              View source
            </a>
          </div>
          <p className="mt-4 text-sm text-faint">
            The tagged release in the repository changelog is{" "}
            <a className="link" href={RELEASE_010_URL}>
              0.1.0
            </a>
            . The ten capabilities on this site are the v{PRODUCT.versionLabel} surface.
          </p>
        </div>
        <Terminal />
      </div>
    </section>
  );
}
