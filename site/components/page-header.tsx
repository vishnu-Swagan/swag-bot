import Link from "next/link";

export function PageHeader({
  eyebrow,
  title,
  lede,
  crumbs,
}: {
  eyebrow: string;
  title: string;
  lede: string;
  crumbs: { href?: string; label: string }[];
}) {
  return (
    <header className="mx-auto w-full max-w-3xl px-4 pb-8 pt-12 md:px-6 md:pt-16">
      <nav aria-label="Breadcrumb">
        <ol className="flex flex-wrap gap-2 font-mono text-xs text-faint">
          <li>
            <Link href="/" className="hover:text-text">
              Home
            </Link>
          </li>
          {crumbs.map((crumb) => (
            <li key={crumb.label} className="flex gap-2">
              <span aria-hidden="true">/</span>
              {crumb.href ? (
                <Link href={crumb.href} className="hover:text-text">
                  {crumb.label}
                </Link>
              ) : (
                <span aria-current="page">{crumb.label}</span>
              )}
            </li>
          ))}
        </ol>
      </nav>
      <p className="kicker mt-6">{eyebrow}</p>
      <h1 className="h-display mt-3 text-4xl sm:text-5xl">{title}</h1>
      <p className="mt-4 text-lg text-muted">{lede}</p>
    </header>
  );
}
