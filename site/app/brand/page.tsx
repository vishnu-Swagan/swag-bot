import { Logo } from "@/components/logo";
import { PageHeader } from "@/components/page-header";
import { pageMeta } from "@/lib/metadata";
import { OWNER, PRODUCT } from "@/lib/site";

export const metadata = pageMeta(
  "Brand",
  "How to use the Swag Bot name and mark. The MIT license does not grant trademark rights.",
  "/brand",
);

export default function BrandPage() {
  return (
    <article>
      <PageHeader
        eyebrow="Brand"
        title="Name and mark"
        lede="Use the name Swag Bot for this project. The MIT license covers the code. It does not grant trademark rights in the name."
        crumbs={[{ label: "Brand" }]}
      />
      <div className="mx-auto grid w-full max-w-3xl gap-4 px-4 pb-20 md:px-6">
        <div className="panel flex items-center gap-4 p-5">
          <Logo className="h-12 w-12" />
          <div>
            <p className="font-semibold">Swag Bot</p>
            <p className="text-sm text-muted">The mark on this site is a check in a rounded square.</p>
          </div>
        </div>
        <h2 className="mt-4 text-2xl font-semibold tracking-tight">Usage</h2>
        <ul className="grid list-disc gap-2 pl-5 text-muted">
          <li>Write the product name as “Swag Bot”, two words, in prose.</li>
          <li>
            The command-line tool is <span className="font-mono">swag</span>. The Python package name is swag-bot.
          </li>
          <li>Do not change the mark’s geometry when you reproduce it, and do not imply that {PRODUCT.author} endorses a fork or a service.</li>
          <li>A fork may say it is a fork of Swag Bot. It should not present its releases as the official build.</li>
          <li>Editorial writing may use the name to refer to the project. That is nominative use, not a license to brand another product with it.</li>
        </ul>
        <p className="text-sm text-muted">
          Trademark filing status: {OWNER.entity} has not published a registration number here. Do not add a ® or ™ unless the owner confirms one.
        </p>
        <p>
          The mark file is{" "}
          <a className="link" href="/mark.svg">
            /mark.svg
          </a>
          . Questions about the name go to {OWNER.email}.
        </p>
      </div>
    </article>
  );
}
