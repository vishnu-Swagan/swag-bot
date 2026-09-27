import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import {
  CONTRIBUTING_URL,
  DISCUSSIONS_URL,
  DOCS,
} from "@/lib/docs-links";
import { GITHUB_URL, GITHUB_USER_URL, PRODUCT } from "@/lib/site";
import Link from "next/link";

const columns = [
  {
    title: "Product",
    links: [
      ["Features", "/features"],
      ["Plugins", "/plugins"],
      ["Changelog", "/changelog"],
      ["Security", "/security"],
      ["Brand", "/brand"],
    ],
  },
  {
    title: "Docs",
    links: [
      ["Docs hub", "/docs"],
      ...DOCS.map((doc) => [doc.title, `/docs/${doc.slug}`] as const),
    ],
  },
  {
    title: "Community",
    links: [
      ["Contributing", "/community"],
      ["GitHub", GITHUB_URL],
      ["Discussions", DISCUSSIONS_URL],
      ["Contributing guide", CONTRIBUTING_URL],
    ],
  },
  {
    title: "Legal",
    links: [
      ["Terms of Use", "/legal/terms"],
      ["Privacy Policy", "/legal/privacy"],
      ["Disclaimer", "/legal/disclaimer"],
      ["MIT license", "/legal/license"],
      ["Acceptable Use", "/legal/acceptable-use"],
    ],
  },
  {
    title: "Company",
    links: [
      ["Vishnu M", GITHUB_USER_URL],
      ["GitHub", GITHUB_URL],
    ],
  },
] as const;

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid w-full max-w-6xl gap-10 px-4 py-14 md:px-6 lg:grid-cols-[1.2fr_2.4fr]">
        <div>
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <Logo />
            Swag Bot
          </Link>
          <p className="mt-4 max-w-xs text-sm text-muted">
            Free, MIT-licensed general agent by {PRODUCT.author}. A step is done only when the evidence agrees.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <ThemeToggle />
            <span className="rounded-full border border-line px-3 py-2 text-sm text-faint">
              X — placeholder
            </span>
            <span className="rounded-full border border-line px-3 py-2 text-sm text-faint">
              Discord — placeholder
            </span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-3 lg:grid-cols-5">
          {columns.map((column) => (
            <div key={column.title}>
              <h2 className="text-sm font-semibold">{column.title}</h2>
              <ul className="mt-3 grid gap-2">
                {column.links.map(([label, href]) => (
                  <li key={href + label}>
                    {href.startsWith("http") ? (
                      <a className="text-sm text-muted hover:text-text" href={href}>
                        {label}
                      </a>
                    ) : (
                      <Link className="text-sm text-muted hover:text-text" href={href}>
                        {label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
      <div className="border-t border-line">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 px-4 py-5 text-sm text-faint md:flex-row md:items-center md:justify-between md:px-6">
          <p>
            MIT License. Copyright 2026 {PRODUCT.author} / {PRODUCT.githubUser}.
          </p>
          <p>Made by {PRODUCT.author}.</p>
        </div>
      </div>
    </footer>
  );
}
