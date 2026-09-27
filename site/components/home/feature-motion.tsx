"use client";

import { useEffect } from "react";

/** Loads Framer Motion only after a feature is chosen, so the first paint does not pay for it. */
export function FeatureMotion() {
  useEffect(() => {
    const root = document.getElementById("feature-picker");
    if (!root) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const onChange = () => {
      const checked = root.querySelector<HTMLInputElement>('input[name="feature"]:checked');
      const slug = checked?.id.replace(/^feature-/, "");
      const panel = slug ? root.querySelector<HTMLElement>(`[data-feature="${slug}"]`) : null;
      if (!panel) return;
      void import("framer-motion").then(({ animate }) => {
        animate(panel, { opacity: [0.55, 1], y: [8, 0] }, { duration: 0.35, ease: [0.22, 1, 0.36, 1] });
      });
    };

    root.addEventListener("change", onChange);
    return () => root.removeEventListener("change", onChange);
  }, []);

  return null;
}
