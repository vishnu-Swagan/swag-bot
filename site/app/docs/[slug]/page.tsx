import { DocBody } from "@/components/doc-body";
import { PageHeader } from "@/components/page-header";
import { DOCS, getDoc } from "@/lib/docs";
import { pageMeta } from "@/lib/metadata";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

type Params = { slug: string };

export function generateStaticParams() {
  return DOCS.map((doc) => ({ slug: doc.slug }));
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) return {};
  return pageMeta(doc.title, doc.lede, `/docs/${doc.slug}`);
}

export default async function DocPage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const doc = getDoc(slug);
  if (!doc) notFound();

  return (
    <article>
      <PageHeader
        eyebrow="Docs"
        title={doc.title}
        lede={doc.lede}
        crumbs={[{ href: "/docs", label: "Docs" }, { label: doc.title }]}
      />
      <div className="mx-auto w-full max-w-3xl px-4 md:px-6">
        <p className="text-sm text-muted">
          Source:{" "}
          <a className="link" href={doc.sourceHref}>
            {doc.sourceLabel}
          </a>
        </p>
      </div>
      <DocBody blocks={doc.blocks} />
    </article>
  );
}
