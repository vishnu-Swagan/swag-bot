"use client";

import { GITHUB_URL, INSTALL_COMMAND, RELEASE_URL, VERSION } from "@/lib/content";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { CopyButton } from "./CopyButton";
import { LoopMark } from "./LoopMark";
import { Outbound } from "./Outbound";

const HeroCanvas = dynamic(() => import("@/components/HeroCanvas"), { ssr: false });

function canUseWebGL() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  if (window.matchMedia("(max-width: 47.99rem)").matches) return false;
  const nav = navigator as Navigator & {
    deviceMemory?: number;
    connection?: { saveData?: boolean };
  };
  if (nav.connection?.saveData) return false;
  if ((nav.deviceMemory ?? 8) <= 2) return false;
  if ((navigator.hardwareConcurrency ?? 8) <= 2) return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

export function Hero() {
  const pointer = useRef({ x: 0, y: 0 });
  const scroll = useRef(0);
  const frame = useRef<HTMLDivElement>(null);
  const [webgl, setWebgl] = useState(false);
  const [ready, setReady] = useState(false);
  const [active, setActive] = useState(true);

  useEffect(() => {
    setWebgl(canUseWebGL());
    const onScroll = () => {
      scroll.current = Math.min(1, window.scrollY / Math.max(window.innerHeight, 1));
    };
    const onMove = (event: PointerEvent) => {
      const box = frame.current?.getBoundingClientRect();
      if (!box) return;
      pointer.current = {
        x: ((event.clientX - box.left) / box.width - 0.5) * 2,
        y: ((event.clientY - box.top) / box.height - 0.5) * 2,
      };
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pointermove", onMove, { passive: true });
    const node = frame.current;
    const observer = new IntersectionObserver(
      ([entry]) => setActive(entry.isIntersecting),
      { threshold: 0.05 },
    );
    if (node) observer.observe(node);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onMove);
      observer.disconnect();
    };
  }, []);

  return (
    <section id="top" className="mx-auto grid max-w-6xl items-center gap-10 px-5 pb-16 pt-28 md:grid-cols-[1.12fr_0.88fr] md:px-8 md:pb-24 md:pt-32">
      <div className="max-w-xl">
        <p className="mono mb-5 text-sm text-faint">
          <Outbound href={RELEASE_URL} className="text-paper underline decoration-lime/70 underline-offset-4">
            v{VERSION}
          </Outbound>
          <span aria-hidden="true"> · </span>
          first release
          <span aria-hidden="true"> · </span>
          MIT
          <span aria-hidden="true"> · </span>
          free
        </p>
        <h1 className="display text-[clamp(3.1rem,7vw,5.5rem)]">
          <span className="block text-violet">Plans the work.</span>
          <span className="block text-coral">Does it.</span>
          <span className="block text-mint">Checks it.</span>
        </h1>
        <p className="mt-6 max-w-prose text-lg text-muted">
          Swag Bot is a free, open-source Python agent. You give it a goal in the terminal.
          It makes a plan, carries the steps out, and verifies the result.
        </p>
        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="install-bar min-w-0 flex-1">
            <code>{INSTALL_COMMAND}</code>
            <CopyButton value={INSTALL_COMMAND} label="Copy" className="btn min-h-11 px-4" />
          </div>
          <Outbound href={GITHUB_URL} className="btn btn-ghost">
            GitHub
          </Outbound>
        </div>
        <p className="mt-4 text-sm text-faint">
          Needs Python 3.11 or newer. Ollama is the default, so you do not need an API key.
        </p>
      </div>
      <div ref={frame} className="relative mx-auto aspect-square w-full max-w-[300px] md:max-w-[520px]">
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background:
              "radial-gradient(circle at 50% 42%, rgba(226,255,87,0.16), transparent 46%), radial-gradient(circle at 30% 72%, rgba(215,198,255,0.14), transparent 36%), radial-gradient(circle at 72% 70%, rgba(142,240,210,0.12), transparent 34%)",
          }}
          aria-hidden="true"
        />
        <div className={`absolute inset-[6%] transition-opacity duration-500 ${ready ? "opacity-0" : "opacity-100"}`}>
          <LoopMark />
        </div>
        {webgl ? (
          <div className={`absolute inset-0 transition-opacity duration-500 ${ready ? "opacity-100" : "opacity-0"}`}>
            <HeroCanvas
              pointer={pointer}
              scroll={scroll}
              active={active}
              onReady={() => setReady(true)}
            />
          </div>
        ) : null}
        <p className="absolute inset-x-0 -bottom-1 text-center text-sm" aria-label="The loop">
          <span className="text-violet">Plan</span>
          <span className="mx-2 text-faint" aria-hidden="true">→</span>
          <span className="text-coral">Do</span>
          <span className="mx-2 text-faint" aria-hidden="true">→</span>
          <span className="text-mint">Verify</span>
        </p>
      </div>
    </section>
  );
}
