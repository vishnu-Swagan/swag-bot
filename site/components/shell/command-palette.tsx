"use client";

import { searchEntries, type SearchEntry } from "@/lib/site";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";

const ENTRIES = searchEntries();

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const results = useMemo(() => filter(query), [query]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("swag-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("swag-palette", onOpen);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    setQuery("");
    setActive(0);
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  function go(entry: SearchEntry | undefined) {
    if (!entry) return;
    setOpen(false);
    router.push(entry.href);
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]" role="presentation">
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        aria-label="Close search"
        onClick={() => setOpen(false)}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search pages"
        className="panel relative z-10 w-full max-w-xl overflow-hidden shadow-[var(--shadow)]"
      >
        <label className="sr-only" htmlFor={`${listId}-q`}>
          Search docs and pages
        </label>
        <input
          id={`${listId}-q`}
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search docs and pages"
          className="w-full border-b border-line bg-transparent px-4 py-4 text-base outline-none"
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={results[active] ? `${listId}-${active}` : undefined}
          autoComplete="off"
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((index) => Math.min(results.length - 1, index + 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((index) => Math.max(0, index - 1));
            } else if (event.key === "Enter") {
              event.preventDefault();
              go(results[active]);
            }
          }}
        />
        <ul id={listId} role="listbox" aria-label="Results" className="max-h-80 overflow-auto py-2">
          {results.length === 0 ? (
            <li className="px-4 py-6 text-sm text-muted">No matching page.</li>
          ) : (
            results.map((entry, index) => (
              <li key={entry.href} role="presentation">
                <button
                  id={`${listId}-${index}`}
                  type="button"
                  role="option"
                  aria-selected={index === active}
                  className={`flex w-full items-baseline justify-between gap-4 px-4 py-2.5 text-left ${
                    index === active ? "bg-elev-2" : ""
                  }`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => go(entry)}
                >
                  <span>{entry.title}</span>
                  <span className="font-mono text-xs text-faint">{entry.group}</span>
                </button>
              </li>
            ))
          )}
        </ul>
        <p className="border-t border-line px-4 py-2 font-mono text-xs text-faint">
          ↑↓ to move · Enter to open · Esc to close
        </p>
      </div>
    </div>
  );
}

function filter(query: string): SearchEntry[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return ENTRIES.slice(0, 8);
  return ENTRIES.filter((entry) =>
    `${entry.title} ${entry.group} ${entry.keywords}`.toLowerCase().includes(needle),
  ).slice(0, 12);
}
