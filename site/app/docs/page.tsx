import { PageHeader } from "@/components/page-header";
import { DOCS } from "@/lib/docs";
import { pageMeta } from "@/lib/metadata";
import { DOCS_REPO_URL } from "@/lib/site";
import Link from "next/link";

export const metadata = pageMeta(
  "Docs",
  "Quickstart, models, plugins, MCP, the evidence spec, and the CLI reference for Swag Bot.",
  "/docs",
);

export default function DocsPage() {
  return (
    <article>
      <PageHeader
        eyebrow="Docs"
        title="Start here, then go to the repository"
        lede="These pages are the readable path. The long-form sources live in the GitHub repository, and each page links to the file it follows."
        crumbs={[{ label: "Docs" }]}
      />
      <div className="mx-auto w-full max-w-3xl px-4 pb-20 md:px-6">
        <ul className="grid gap-3">
          {DOCS.map((doc) => (
            <li key={doc.slug}>
              <Link href={`/docs/${doc.slug}`} className="panel block p-5 hover:border-line-strong">
                <span className="text-xl font-semibold tracking-tight">{doc.title}</span>
                <span className="mt-2 block text-muted">{doc.lede}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-8 text-sm text-muted">
          Repository docs:{" "}
          <a className="link" href={DOCS_REPO_URL}>
            github.com/vishnu-Swagan/swag-bot/tree/main/docs
          </a>
        </p>
      </div>
    </article>
  );
}
