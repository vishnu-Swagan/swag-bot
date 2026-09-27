import { PageHeader } from "@/components/page-header";
import { pageMeta } from "@/lib/metadata";
import { GITHUB_URL, ISSUES_URL, OWNER } from "@/lib/site";

export const metadata = pageMeta(
  "Security",
  "Report a vulnerability in Swag Bot privately. A SECURITY.md file is not in the repository yet.",
  "/security",
);

export default function SecurityPage() {
  return (
    <article>
      <PageHeader
        eyebrow="Security"
        title="Responsible disclosure"
        lede="If you believe you have found a vulnerability in Swag Bot, please report it privately. A SECURITY.md file is not in the repository yet. Until one exists, this page is the contact."
        crumbs={[{ label: "Security" }]}
      />
      <div className="mx-auto grid w-full max-w-3xl gap-4 px-4 pb-20 md:px-6">
        <p>
          Contact: <span className="font-mono text-sm">{OWNER.email}</span>
        </p>
        <p>
          Please include a description, the version or commit you tested, and enough detail to reproduce the issue. Give the maintainer time to respond before any public write-up.
        </p>
        <p>Do not open a public GitHub issue for an undisclosed vulnerability. Public issues are fine for bugs that are not security-sensitive.</p>
        <ul className="grid gap-2 text-sm">
          <li>
            <a className="link" href={ISSUES_URL}>
              GitHub issues
            </a>
          </li>
          <li>
            <a className="link" href={GITHUB_URL}>
              Repository
            </a>
          </li>
        </ul>
        <p className="text-sm text-muted">
          The entity that receives reports is {OWNER.entity}. That field is a placeholder until the owner fills it in.
        </p>
      </div>
    </article>
  );
}
