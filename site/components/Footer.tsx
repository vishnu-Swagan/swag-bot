import {
  DOCS_URL,
  GITHUB_URL,
  LICENSE_URL,
  PLUGIN_GUIDE_URL,
  README_URL,
  RELEASE_URL,
  VERSION,
} from "@/lib/content";
import { Outbound } from "./Outbound";

const LINKS = [
  { href: README_URL, label: "README" },
  { href: DOCS_URL, label: "Docs" },
  { href: PLUGIN_GUIDE_URL, label: "Plugin guide" },
  { href: GITHUB_URL, label: "GitHub" },
  { href: LICENSE_URL, label: "MIT license" },
  { href: RELEASE_URL, label: `v${VERSION} release` },
] as const;

export function Footer() {
  return (
    <footer className="relative z-20 border-t border-line bg-ink px-5 py-14 md:px-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="display text-4xl">Swag Bot</p>
          <p className="mt-2 max-w-md text-muted">
            A free, MIT-licensed agent for complex multi-step tasks. Copyright 2026 Vishnu M /
            vishnu-Swagan.
          </p>
        </div>
        <ul className="flex flex-wrap gap-x-5 gap-y-2">
          {LINKS.map((link) => (
            <li key={link.href}>
              <Outbound href={link.href} className="text-paper underline decoration-white/30 underline-offset-4">
                {link.label}
              </Outbound>
            </li>
          ))}
        </ul>
      </div>
    </footer>
  );
}
