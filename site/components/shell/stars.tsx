"use client";

import { GITHUB_URL, STARS_API } from "@/lib/site";
import { useEffect, useState } from "react";

export function Stars({ compact = false }: { compact?: boolean }) {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    if (connection?.saveData) return;
    const controller = new AbortController();
    fetch(STARS_API, { signal: controller.signal, headers: { Accept: "application/vnd.github+json" } })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("stars"))))
      .then((data: { stargazers_count?: unknown }) => {
        if (typeof data.stargazers_count === "number") setStars(data.stargazers_count);
      })
      .catch(() => {
        /* keep the button, omit the count */
      });
    return () => controller.abort();
  }, []);

  return (
    <a className="btn btn-ghost min-h-11" href={GITHUB_URL}>
      <span>GitHub</span>
      {stars !== null ? (
        <span className="font-mono text-sm tabular-nums">{stars.toLocaleString("en-US")}</span>
      ) : (
        <span className="sr-only">{compact ? "" : "Star count unavailable"}</span>
      )}
    </a>
  );
}
