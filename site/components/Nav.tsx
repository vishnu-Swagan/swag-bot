"use client";

import { GITHUB_URL, NAV_LINKS } from "@/lib/content";
import { useEffect, useId, useState } from "react";
import { Outbound } from "./Outbound";

export function Nav() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [current, setCurrent] = useState("");
  const panelId = useId();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const sections = NAV_LINKS.map((link) => document.querySelector(link.href)).filter(
      (node): node is Element => node instanceof Element,
    );
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target.id) setCurrent(`#${visible.target.id}`);
      },
      { rootMargin: "-40% 0px -45% 0px", threshold: [0.1, 0.25, 0.5] },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 border-b backdrop-blur-md ${
        scrolled ? "border-line bg-ink/80" : "border-transparent bg-ink/45"
      }`}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-3 md:px-8">
        <a href="#top" className="flex items-center gap-2 text-paper no-underline">
          <Mark />
          <span className="display text-xl tracking-tight">Swag Bot</span>
        </a>
        <nav className="hidden items-center gap-6 md:flex" aria-label="Page">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="nav-link"
              aria-current={current === link.href ? "true" : undefined}
            >
              {link.label}
            </a>
          ))}
          <Outbound href={GITHUB_URL} className="btn btn-ghost min-h-11 px-4 text-sm">
            GitHub
          </Outbound>
        </nav>
        <button
          type="button"
          className="btn btn-ghost min-h-11 px-4 md:hidden"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Close" : "Menu"}
        </button>
      </div>
      {open ? (
        <nav id={panelId} className="border-t border-line px-5 py-4 md:hidden" aria-label="Page">
          <ul className="flex flex-col gap-1">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  className="nav-link block rounded-xl px-2 py-3 text-lg"
                  onClick={() => setOpen(false)}
                >
                  {link.label}
                </a>
              </li>
            ))}
            <li className="pt-2">
              <Outbound href={GITHUB_URL} className="btn btn-ghost w-full">
                GitHub
              </Outbound>
            </li>
          </ul>
        </nav>
      ) : null}
    </header>
  );
}

function Mark() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="6.5" r="3.1" fill="#d7c6ff" />
      <circle cx="6.5" cy="24" r="3.1" fill="#ff8a5c" />
      <circle cx="25.5" cy="24" r="3.1" fill="#8ef0d2" />
      <circle cx="16" cy="16" r="2.3" fill="#e2ff57" />
    </svg>
  );
}
