"use client";

import { useState } from "react";

type CopyButtonProps = {
  value: string;
  label?: string;
  className?: string;
};

export function CopyButton({ value, label = "Copy", className }: CopyButtonProps) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 2200);
  }

  const text = state === "copied" ? "Copied" : state === "failed" ? "Select it" : label;
  const live =
    state === "copied"
      ? "Copied."
      : state === "failed"
        ? "Could not copy. Select the command and copy it yourself."
        : "";

  return (
    <>
      <button type="button" className={className ?? "btn btn-lime"} onClick={onCopy}>
        {text}
      </button>
      <span className="sr-only" aria-live="polite">
        {live}
      </span>
    </>
  );
}
