import { PageHeader } from "@/components/page-header";
import { pageMeta } from "@/lib/metadata";
import { ARCHITECTURE_URL, CONTRIBUTING_URL, DISCUSSIONS_URL, GITHUB_URL, ISSUES_URL } from "@/lib/site";

export const metadata = pageMeta(
  "Community",
  "How to contribute to Swag Bot. MIT-compatible changes, the checks CI runs, and where to talk.",
  "/community",
);

export default function CommunityPage() {
  return (
    <article>
      <PageHeader
        eyebrow="Community"
        title="Contributing"
        lede="Swag Bot is MIT licensed. Contributions should stay MIT-compatible. The guide in the repository is the source for this page."
        crumbs={[{ label: "Community" }]}
      />
      <div className="mx-auto grid w-full max-w-3xl gap-4 px-4 pb-20 md:px-6">
        <h2 className="text-2xl font-semibold tracking-tight">Setup</h2>
        <p>Python 3.11 or newer.</p>
        <pre className="overflow-x-auto rounded-2xl border border-line bg-elev p-4 font-mono text-sm">
          <code>python -m pip install -e ".[dev]"</code>
        </pre>
        <p>API keys stay in the environment. Do not commit a .env, tokens, or real credentials. SWAG_HOME overrides ~/.swag. The test suite sets it to a temporary directory.</p>
        <h2 className="mt-4 text-2xl font-semibold tracking-tight">Checks</h2>
        <pre className="overflow-x-auto rounded-2xl border border-line bg-elev p-4 font-mono text-sm">
          <code>{`ruff check .\nmypy\npytest`}</code>
        </pre>
        <p>CI runs ruff, mypy, and pytest on Python 3.11 and 3.12. It does not install the optional models, mcp, sandbox, or graphbit extras. mypy is strict on the swag_bot package.</p>
        <h2 className="mt-4 text-2xl font-semibold tracking-tight">Boundaries</h2>
        <ul className="grid list-disc gap-2 pl-5 text-muted">
          <li>Do not copy AGPL, SSPL, or other network-copyleft source into the repository, and do not add those licenses as dependencies.</li>
          <li>Owned packages do not import each other. They depend on interfaces, config, and errors.</li>
          <li>Changes to interfaces.py are additive. New fields need defaults.</li>
          <li>Do not store secrets in config.</li>
          <li>Open a pull request against main. Describe what changed and how you tested it.</li>
        </ul>
        <h2 className="mt-4 text-2xl font-semibold tracking-tight">Talk</h2>
        <ul className="grid gap-2">
          <li>
            <a className="link" href={CONTRIBUTING_URL}>
              CONTRIBUTING.md
            </a>
          </li>
          <li>
            <a className="link" href={ARCHITECTURE_URL}>
              Architecture
            </a>
          </li>
          <li>
            <a className="link" href={DISCUSSIONS_URL}>
              GitHub discussions
            </a>
          </li>
          <li>
            <a className="link" href={ISSUES_URL}>
              Issues
            </a>
          </li>
          <li>
            <a className="link" href={GITHUB_URL}>
              Repository
            </a>
          </li>
        </ul>
        <p className="text-sm text-muted">X and Discord are placeholders in the footer. There is no official account to link yet.</p>
      </div>
    </article>
  );
}
