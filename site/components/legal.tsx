import { PageHeader } from "@/components/page-header";
import { OWNER } from "@/lib/site";
import type { ReactNode } from "react";

export function LegalLayout({
  title,
  lede,
  children,
}: {
  title: string;
  lede: string;
  children: ReactNode;
}) {
  return (
    <article>
      <PageHeader eyebrow="Legal template" title={title} lede={lede} crumbs={[{ label: title }]} />
      <div className="mx-auto w-full max-w-3xl px-4 pb-6 md:px-6">
        <p className="rounded-2xl border border-line bg-elev px-4 py-3 text-sm text-muted">
          These legal pages are templates. They are not legal advice and have not been reviewed by a lawyer. Replace {OWNER.entity}, {OWNER.email}, and {OWNER.jurisdiction} before relying on them.
        </p>
      </div>
      <div className="mx-auto grid w-full max-w-3xl gap-4 px-4 pb-20 text-[1.02rem] md:px-6">{children}</div>
    </article>
  );
}

export function H2({ children }: { children: ReactNode }) {
  return <h2 className="mt-6 text-2xl font-semibold tracking-tight">{children}</h2>;
}
