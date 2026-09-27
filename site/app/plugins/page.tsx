import { PageHeader } from "@/components/page-header";
import { pageMeta } from "@/lib/metadata";
import { EXAMPLE_PLUGIN_URL } from "@/lib/site";
import Link from "next/link";

const PLACEHOLDERS = [
  {
    name: "Listing slot A",
    note: "Coming soon. No plugin is published in this slot.",
  },
  {
    name: "Listing slot B",
    note: "Coming soon. No plugin is published in this slot.",
  },
  {
    name: "Listing slot C",
    note: "Coming soon. No plugin is published in this slot.",
  },
];

export const metadata = pageMeta(
  "Plugins",
  "The signed Swag Bot plugin gallery is not populated on this site yet. Every card is marked coming soon.",
  "/plugins",
);

export default function PluginsPage() {
  return (
    <article>
      <PageHeader
        eyebrow="Gallery"
        title="Signed plugins, catalog not open"
        lede="Gallery plugins are signed with minisign and scanned. This page does not pretend the catalog is live. Every card says coming soon."
        crumbs={[{ label: "Plugins" }]}
      />
      <div className="mx-auto grid w-full max-w-3xl gap-4 px-4 pb-20 md:px-6">
        <article className="panel p-5">
          <p className="font-mono text-xs text-warn">In the repository · gallery listing coming soon</p>
          <h2 className="mt-3 text-xl font-semibold">example-github-helper</h2>
          <p className="mt-2 text-muted">
            A sample Cowork-style plugin that ships in the repository: a skill, a slash command, and an agent. You can validate it locally. It is not a signed gallery listing.
          </p>
          <a className="link mt-4 inline-flex" href={EXAMPLE_PLUGIN_URL}>
            Open the sample on GitHub
          </a>
        </article>
        {PLACEHOLDERS.map((slot) => (
          <article key={slot.name} className="rounded-2xl border border-dashed border-line p-5">
            <p className="font-mono text-xs text-faint">Coming soon</p>
            <h2 className="mt-3 text-xl font-semibold">{slot.name}</h2>
            <p className="mt-2 text-muted">{slot.note}</p>
          </article>
        ))}
        <p className="text-sm text-muted">
          Authoring notes are in the{" "}
          <Link className="link" href="/docs/plugins">
            plugins and skills doc
          </Link>
          .
        </p>
      </div>
    </article>
  );
}
