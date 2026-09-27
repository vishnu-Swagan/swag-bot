import { H2, LegalLayout } from "@/components/legal";
import { pageMeta } from "@/lib/metadata";
import { GITHUB_URL, OWNER, PRODUCT } from "@/lib/site";

export const metadata = pageMeta(
  "Terms of Use",
  "Template terms for the Swag Bot website and project. Not legal advice. Owner fields are unconfirmed.",
  "/legal/terms",
);

export default function TermsPage() {
  return (
    <LegalLayout
      title="Terms of Use"
      lede="These terms cover the website. The software itself is offered under the MIT license."
    >
      <p>
        The website is published by {OWNER.entity} (“we”). The maintainer named on the project is {PRODUCT.author}. Contact: {OWNER.email}.
      </p>
      <H2>The software</H2>
      <p>
        Swag Bot is free software under the MIT license. That license, not these website terms, governs your rights to copy and modify the code. Read the{" "}
        <a className="link" href="/legal/license">
          license page
        </a>{" "}
        and the{" "}
        <a className="link" href={GITHUB_URL}>
          repository
        </a>
        .
      </p>
      <H2>The website</H2>
      <p>
        You may read these pages and share links to them. You may not misrepresent the project, scrape the site in a way that degrades it for other people, or present modified copies of these pages as the official site.
      </p>
      <H2>No account</H2>
      <p>This website does not offer user accounts. The CLI runs on your machine.</p>
      <H2>Disclaimers</H2>
      <p>
        The site and the software are provided without warranty. Model output can be wrong. You are responsible for actions you approve. See the disclaimer.
      </p>
      <H2>Governing law</H2>
      <p>
        These website terms are governed by the laws of {OWNER.jurisdiction}, excluding conflict-of-law rules, once that placeholder is replaced. Until then, do not treat this sentence as a choice of law.
      </p>
      <H2>Changes</H2>
      <p>We may update these terms by publishing a new version on this page. The software license for a release you already received does not change when this page changes.</p>
    </LegalLayout>
  );
}
