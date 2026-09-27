import { H2, LegalLayout } from "@/components/legal";
import { pageMeta } from "@/lib/metadata";
import { OWNER } from "@/lib/site";

export const metadata = pageMeta(
  "Acceptable Use",
  "Template acceptable-use rules for Swag Bot. Not legal advice. Owner fields are unconfirmed.",
  "/legal/acceptable-use",
);

export default function AcceptableUsePage() {
  return (
    <LegalLayout
      title="Acceptable Use"
      lede="The software is a local agent you run. These rules describe uses the project does not support."
    >
      <p>
        Published by {OWNER.entity}. Contact: {OWNER.email}. Governing-law placeholder: {OWNER.jurisdiction}.
      </p>
      <H2>Do not use Swag Bot to</H2>
      <ul className="grid list-disc gap-2 pl-5">
        <li>break the law, or help someone else break the law;</li>
        <li>access, disrupt, or take data from a system, account, or network without authorization;</li>
        <li>distribute malware, or hide what the agent is doing from the person who must approve it;</li>
        <li>generate or spread sexual content involving minors;</li>
        <li>impersonate {OWNER.entity}, Vishnu M, or the official project.</li>
      </ul>
      <H2>Your approvals</H2>
      <p>
        You are responsible for the permissions you grant, the plugins you install, the MCP servers you connect, and the model provider you choose. A signed gallery and a scanner are not a promise that every future plugin is safe.
      </p>
      <H2>Enforcement</H2>
      <p>
        This is a free open-source project without a hosted agent service. There is no account to suspend. The maintainer may still refuse a contribution, close an issue, or state publicly that a use is outside these rules.
      </p>
      <p>This page is a template and is not legal advice.</p>
    </LegalLayout>
  );
}
