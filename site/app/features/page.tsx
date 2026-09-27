import { PageHeader } from "@/components/page-header";
import { pageMeta } from "@/lib/metadata";
import { FEATURES } from "@/lib/site";
import Link from "next/link";

export const metadata = pageMeta(
  "Features",
  "Ten Swag Bot capabilities: proof checks, handoff, setup, a small-model harness, undo, a signed gallery, a taint firewall, verified skills, a jury, and run bundles.",
  "/features",
);

export default function FeaturesPage() {
  return (
    <article>
      <PageHeader
        eyebrow="Product"
        title="Ten things the run can show"
        lede="Each page is one capability from the v0.2 surface. The concrete fact on the card is the whole claim. There is no extra statistic behind it."
        crumbs={[{ label: "Features" }]}
      />
      <ol className="mx-auto grid w-full max-w-3xl gap-3 px-4 pb-20 md:px-6">
        {FEATURES.map((feature) => (
          <li key={feature.slug}>
            <Link href={`/features/${feature.slug}`} className="panel block p-5 hover:border-line-strong">
              <span className="font-mono text-xs text-faint">{feature.index}</span>
              <span className="mt-2 block text-xl font-semibold tracking-tight">{feature.title}</span>
              <span className="mt-2 block text-muted">{feature.summary}</span>
            </Link>
          </li>
        ))}
      </ol>
    </article>
  );
}
