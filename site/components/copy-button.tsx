"use client";

import { useState } from "react";

export function CopyButton({
  text,
  label = "Copy",
  className = "",
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "done" | "error">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("done");
    } catch {
      setState("error");
    }
    window.setTimeout(() => setState("idle"), 1800);
  }

  const status = state === "done" ? "Copied" : state === "error" ? "Copy failed" : label;

  return (
    <button type="button" className={`btn btn-ghost ${className}`} onClick={copy}>
      {status}
      <span className="sr-only" aria-live="polite">
        {state === "done" ? "Command copied" : state === "error" ? "Could not copy" : ""}
      </span>
    </button>
  );
}
