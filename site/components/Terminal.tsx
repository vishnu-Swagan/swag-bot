"use client";

import { DOCTOR_ROWS } from "@/lib/content";
import { useEffect, useRef, useState } from "react";

const LINES = [
  { kind: "cmd" as const, text: "swag version" },
  { kind: "out" as const, text: "swag-bot 0.1.0" },
  { kind: "blank" as const, text: "" },
  { kind: "cmd" as const, text: "swag doctor" },
  ...DOCTOR_ROWS.map((row) => ({
    kind: "out" as const,
    text: `${row[0].padEnd(20, " ")}${row[1]}`,
  })),
  { kind: "out" as const, text: "API keys are read from the environment and are not displayed." },
  { kind: "blank" as const, text: "" },
  { kind: "cmd" as const, text: 'swag run "Summarize the files in this directory"' },
  { kind: "out" as const, text: "Planning: Summarize the files in this directory" },
];

function renderLine(line: (typeof LINES)[number]) {
  if (line.kind === "blank") return "\n";
  if (line.kind === "cmd") return `$ ${line.text}\n`;
  return `${line.text}\n`;
}

const TRANSCRIPT = LINES.map(renderLine).join("");

export function Terminal() {
  const [count, setCount] = useState(0);
  const [playing, setPlaying] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !document.documentElement.classList.contains("js-motion")) {
      setCount(LINES.length);
      return;
    }
    const node = root.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setPlaying(true);
      },
      { threshold: 0.35 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!playing || count >= LINES.length) return;
    const delay = LINES[count]?.kind === "blank" ? 180 : 90;
    const timer = window.setTimeout(() => setCount((value) => value + 1), delay);
    return () => window.clearTimeout(timer);
  }, [playing, count]);

  const shown = LINES.slice(0, count).map(renderLine).join("");

  return (
    <div ref={root} className="mt-8 min-w-0 overflow-hidden rounded-[1.4rem] border border-line bg-[#16130f]">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <p className="mono text-sm text-muted">Illustrated quickstart</p>
        <button
          type="button"
          className="btn btn-ghost min-h-11 px-3 text-sm"
          onClick={() => {
            setCount(0);
            setPlaying(true);
          }}
        >
          Replay
        </button>
      </div>
      <pre className="terminal-static mono m-0 overflow-x-auto p-4 text-sm leading-6 text-paper">
        {TRANSCRIPT}
      </pre>
      <pre className="terminal-live mono m-0 min-h-72 overflow-x-auto p-4 text-sm leading-6 text-paper" aria-hidden="true">
        {shown}
        <span className="text-lime">▍</span>
      </pre>
    </div>
  );
}
