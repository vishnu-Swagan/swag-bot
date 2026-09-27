import { PageHeader } from "@/components/page-header";
import { pageMeta } from "@/lib/metadata";
import { CHANGELOG_URL, FEATURES, RELEASE_010_URL } from "@/lib/site";
import Link from "next/link";

export const metadata = pageMeta(
  "Changelog",
  "Swag Bot v0.2 is on main. A tagged release is coming. 0.1.0 is the previous tagged release.",
  "/changelog",
);

export default function ChangelogPage() {
  return (
    <article>
      <PageHeader
        eyebrow="Changelog"
        title="v0.2 is on main"
        lede="The ten capabilities below are in the main branch. A tagged release is coming. 0.1.0 remains the previous tagged release."
        crumbs={[{ label: "Changelog" }]}
      />
      <div className="mx-auto grid w-full max-w-3xl gap-10 px-4 pb-20 md:px-6">
        <section>
          <h2 className="text-2xl font-semibold tracking-tight">0.2.0</h2>
          <p className="mt-2 text-sm text-faint">On main as of the 0.2 integration. Not tagged yet. A tagged release is coming. The package version in the tree is still 0.1.0 until that tag.</p>
          <ul className="mt-4 grid gap-2">
            {FEATURES.map((feature) => (
              <li key={feature.slug}>
                <Link className="link" href={`/features/${feature.slug}`}>
                  {feature.title}
                </Link>
                <span className="text-muted"> — {feature.summary}</span>
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h2 className="text-2xl font-semibold tracking-tight">
            <a className="link" href={RELEASE_010_URL}>
              0.1.0
            </a>
          </h2>
          <p className="mt-2 text-sm text-faint">2026-09-27 · tagged release</p>
          <p className="mt-4">
            First tagged release. <span className="font-mono">swag run</span> plans a goal, carries the steps out, and checks its own work.
          </p>
          <ul className="mt-4 grid list-disc gap-2 pl-5 text-muted">
            <li>swag command-line tool: run, doctor, version, and serve-mcp.</li>
            <li>Plan-do-verify loop with parallel independent steps, and an optional GraphBit engine that falls back to the Python scheduler.</li>
            <li>Local sandbox by default, optional Docker sandbox, permission policy (ask-always, ask-risky, auto), and an append-only action log with secret redaction.</li>
            <li>Claude Cowork-compatible plugins, Agent Skills, slash commands, and a marketplace installer. Approving an install writes grants.</li>
            <li>MCP client (stdio and streamable HTTP) and swag serve-mcp (swag_run_task, swag_list_skills).</li>
            <li>Models: Ollama by default. OpenAI, Anthropic, Gemini, and OpenRouter through optional LiteLLM.</li>
            <li>Memory: SQLite by default, a JSON file, or an external agentmemory server.</li>
            <li>Example plugin plugins/example-github-helper.</li>
            <li>PyPI upload stays off unless PUBLISH_PYPI is set. A v* tag still builds a GitHub Release.</li>
          </ul>
          <p className="mt-4 text-sm">
            Full file:{" "}
            <a className="link" href={CHANGELOG_URL}>
              CHANGELOG.md
            </a>
          </p>
        </section>
      </div>
    </article>
  );
}
