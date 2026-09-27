"use client";

export function ThemeToggle({ className = "" }: { className?: string }) {
  function toggle() {
    const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    const next = current === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* private mode */
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", next === "light" ? "#f5f5f2" : "#09090b");
  }

  return (
    <button
      type="button"
      className={`btn btn-ghost min-h-11 min-w-11 px-3 ${className}`}
      onClick={toggle}
      aria-label="Toggle color theme"
    >
      <SunIcon />
      <MoonIcon />
    </button>
  );
}

function SunIcon() {
  return (
    <svg className="icon-sun h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="4" fill="currentColor" />
      <path
        d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5 5l1.6 1.6M17.4 17.4 19 19M19 5l-1.6 1.6M6.6 17.4 5 19"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className="icon-moon h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M16.5 13.2A6.2 6.2 0 0 1 10.6 5 6.4 6.4 0 1 0 19 14.8a6.4 6.4 0 0 1-2.5-1.6Z"
        fill="currentColor"
      />
    </svg>
  );
}
