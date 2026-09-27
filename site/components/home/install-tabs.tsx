"use client";

import { CopyButton } from "@/components/copy-button";
import { INSTALL_TABS } from "@/lib/site";
import { useEffect, useState } from "react";

export function InstallTabs() {
  const [tab, setTab] = useState<(typeof INSTALL_TABS)[number]["id"]>("unix");
  const current = INSTALL_TABS.find((item) => item.id === tab) ?? INSTALL_TABS[0];

  useEffect(() => {
    const platform = navigator.platform || "";
    const ua = navigator.userAgent || "";
    if (/Win/i.test(platform) || /Windows/i.test(ua)) setTab("windows");
  }, []);

  return (
    <div>
      <div role="tablist" aria-label="Install command by operating system" className="flex flex-wrap gap-2">
        {INSTALL_TABS.map((item) => {
          const selected = item.id === current.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`install-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`install-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              className={`min-h-11 rounded-full px-3 text-sm ${selected ? "bg-text text-bg" : "text-muted"}`}
              onClick={() => setTab(item.id)}
              onKeyDown={(event) => {
                const index = INSTALL_TABS.findIndex((entry) => entry.id === current.id);
                if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                  event.preventDefault();
                  const delta = event.key === "ArrowRight" ? 1 : -1;
                  const next = INSTALL_TABS[(index + delta + INSTALL_TABS.length) % INSTALL_TABS.length];
                  setTab(next.id);
                  document.getElementById(`install-tab-${next.id}`)?.focus();
                }
              }}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`install-panel-${current.id}`}
        aria-labelledby={`install-tab-${current.id}`}
        className="mt-3 flex flex-col gap-3 rounded-2xl border border-line bg-elev p-3 sm:flex-row sm:items-center"
      >
        <div className="min-w-0 flex-1 px-2">
          {current.comingSoon ? (
            <p className="font-mono text-xs text-warn">Coming soon. PyPI is not published, so this does not install Swag Bot yet.</p>
          ) : null}
          <code className="mt-1 block overflow-x-auto font-mono text-sm">{current.command}</code>
        </div>
        {current.comingSoon ? null : <CopyButton text={current.command} />}
      </div>
    </div>
  );
}
