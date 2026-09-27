import { MicroDemo } from "@/components/home/micro-demos";
import { PageHeader } from "@/components/page-header";
import { pageMeta } from "@/lib/metadata";
import { FEATURES, getFeature } from "@/lib/site";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

type Params = { slug: string };

export function generateStaticParams() {
  return FEATURES.map((feature) => ({ slug: feature.slug }));
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  const feature = getFeature(slug);
  if (!feature) return {};
  return pageMeta(feature.title, feature.summary, `/features/${feature.slug}`);
}

export default async function FeaturePage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const feature = getFeature(slug);
  if (!feature) notFound();
  const index = FEATURES.findIndex((item) => item.slug === feature.slug);
  const previous = FEATURES[index - 1];
  const next = FEATURES[index + 1];

  return (
    <article>
      <PageHeader
        eyebrow={`Feature ${feature.index}`}
        title={feature.title}
        lede={feature.summary}
        crumbs={[{ href: "/features", label: "Features" }, { label: feature.title }]}
      />
      <div className="mx-auto grid w-full max-w-3xl gap-6 px-4 pb-20 md:px-6">
        <div className="panel p-5">
          <p className="kicker">Recorded fact</p>
          <p className="mt-3 text-lg">{feature.fact}</p>
          <div className="mt-5 rounded-xl border border-line bg-bg p-4">
            <MicroDemo kind={feature.demo} />
          </div>
        </div>
        {feature.body.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
        <nav className="flex flex-wrap gap-4 border-t border-line pt-6 text-sm" aria-label="Feature pages">
          {previous ? (
            <Link className="link" href={`/features/${previous.slug}`}>
              {previous.index} {previous.title}
            </Link>
          ) : null}
          {next ? (
            <Link className="link" href={`/features/${next.slug}`}>
              {next.index} {next.title}
            </Link>
          ) : null}
        </nav>
      </div>
    </article>
  );
}
