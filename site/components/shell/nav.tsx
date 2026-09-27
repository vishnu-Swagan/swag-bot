"use client";

import { Logo } from "@/components/logo";
import { Stars } from "@/components/shell/stars";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { NAV } from "@/lib/site";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export function Nav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>("a, button");
    first?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
      if (event.key !== "Tab" || !panel) return;
      const items = [...panel.querySelectorAll<HTMLElement>("a, button")];
      if (items.length === 0) return;
      const firstItem = items[0];
      const lastItem = items[items.length - 1];
      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <header className="nav-blur sticky top-0 z-40 border-b border-line">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-4 md:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <Logo />
          <span>Swag Bot</span>
        </Link>
        <nav className="ml-6 hidden items-center gap-1 md:flex" aria-label="Primary">
          {NAV.map((item) => {
            const current = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={`rounded-full px-3 py-2 text-sm ${current ? "bg-elev-2 text-text" : "text-muted"}`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            className="btn btn-ghost hidden min-h-11 px-3 sm:inline-flex"
            onClick={() => window.dispatchEvent(new Event("swag-palette"))}
          >
            Search
            <kbd className="font-mono text-xs text-faint">⌘K</kbd>
          </button>
          <div className="hidden sm:block">
            <Stars compact />
          </div>
          <ThemeToggle className="hidden sm:inline-flex" />
          <Link href="/#install" className="btn btn-accent hidden sm:inline-flex">
            Install
          </Link>
          <button
            ref={toggleRef}
            type="button"
            className="btn btn-ghost min-h-11 px-3 md:hidden"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>
      </div>
      {open ? (
        <div
          id="mobile-nav"
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label="Mobile navigation"
          className="border-t border-line bg-bg px-4 py-4 md:hidden"
        >
          <nav className="grid gap-1" aria-label="Mobile">
            {NAV.map((item) => (
              <Link key={item.href} href={item.href} className="rounded-xl px-3 py-3 text-base">
                {item.label}
              </Link>
            ))}
            <Link href="/security" className="rounded-xl px-3 py-3">
              Security
            </Link>
            <Link href="/community" className="rounded-xl px-3 py-3">
              Community
            </Link>
          </nav>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setOpen(false);
                window.dispatchEvent(new Event("swag-palette"));
              }}
            >
              Search
            </button>
            <Stars />
            <ThemeToggle />
            <Link href="/#install" className="btn btn-accent">
              Install
            </Link>
          </div>
        </div>
      ) : null}
    </header>
  );
}
