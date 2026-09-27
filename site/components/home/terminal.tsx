"use client";

import { useEffect, useState } from "react";

const LINES = [
  { kind: "cmd", text: 'swag run "print the 10th Fibonacci number"' },
  { kind: "dim", text: "model qwen2.5:3b · harness tiny · plain CPU" },
  { kind: "dim", text: "plan  1 step" },
  { kind: "out", text: "check  stdout contains 55" },
  { kind: "out", text: "check  process exits 0" },
  { kind: "dim", text: "act" },
  { kind: "evidence", text: "evidence ev_7f3a   exit 0   stdout 55   78s" },
  { kind: "ok", text: "verdict pass   cites ev_7f3a" },
  { kind: "dim", text: "— without the harness, the same 3B model was still failing after ~4 min —" },
  { kind: "cmd", text: 'swag run "run the suite and report"' },
  { kind: "bad", text: 'model   "All tests passed"' },
  { kind: "evidence", text: "evidence ev_91c2   exit 1" },
  { kind: "bad", text: "verdict fail   ev_91c2 contradicts the claim" },
  { kind: "out", text: "status  not done" },
] as const;

const TRANSCRIPT = LINES.map((line) => (line.kind === "cmd" ? `$ ${line.text}` : line.text)).join("\n");

export function Terminal() {
  const [count, setCount] = useState<number>(LINES.length);
  const [paused, setPaused] = useState(false);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      setReduced(media.matches);
      if (media.matches) setCount(LINES.length);
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    if (reduced || paused) return;
    if (count >= LINES.length) {
      const hold = window.setTimeout(() => setCount(0), 2800);
      return () => window.clearTimeout(hold);
    }
    const delay = LINES[count]?.kind === "cmd" ? 700 : 420;
    const timer = window.setTimeout(() => setCount((value) => value + 1), delay);
    return () => window.clearTimeout(timer);
  }, [count, paused, reduced]);

  const visible = LINES.slice(0, reduced ? LINES.length : count);

  return (
    <div className="panel relative overflow-hidden shadow-[var(--shadow)]">
      <div className="sr-only">{TRANSCRIPT}</div>
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <p className="font-mono text-xs text-faint">session · evidence</p>
        <button
          type="button"
          className="rounded-full border border-line px-3 py-1 font-mono text-xs"
          onClick={() => setPaused((value) => !value)}
          aria-pressed={paused || reduced}
        >
          {reduced ? "Still" : paused ? "Play" : "Pause"}
        </button>
      </div>
      <div className="h-[26rem] overflow-hidden px-4 py-4 font-mono text-[13px] leading-6 sm:text-sm" aria-hidden="true">
        {visible.map((line, index) => (
          <div key={`${line.text}-${index}`} className={color(line.kind)}>
            {line.kind === "cmd" ? <span className="text-faint">$ </span> : null}
            {line.text}
            {index === visible.length - 1 && !reduced ? <span className="caret" /> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function color(kind: (typeof LINES)[number]["kind"]) {
  if (kind === "ok") return "text-good";
  if (kind === "bad") return "text-bad";
  if (kind === "evidence") return "text-accent-text";
  if (kind === "dim") return "text-faint";
  return "text-text";
}
