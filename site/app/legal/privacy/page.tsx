import { H2, LegalLayout } from "@/components/legal";
import { pageMeta } from "@/lib/metadata";
import { OWNER } from "@/lib/site";

export const metadata = pageMeta(
  "Privacy Policy",
  "The Swag Bot website does not use tracking cookies or analytics. The CLI has no telemetry and runs locally.",
  "/legal/privacy",
);

export default function PrivacyPage() {
  return (
    <LegalLayout
      title="Privacy Policy"
      lede="What this website does, and what the CLI does not send."
    >
      <p>
        This policy is published by {OWNER.entity}. Contact: {OWNER.email}.
      </p>
      <H2>The website</H2>
      <p>
        As published, this website does not set tracking cookies and does not load analytics or other third-party trackers. A cookie notice is omitted because cookies are not used. If that changes, this page and a cookie notice must change with it.
      </p>
      <p>
        Your theme choice is stored in localStorage on your device under the key “theme”. That is not a cookie, and it is not sent to a server operated by this project.
      </p>
      <p>
        The GitHub star button asks your browser to request https://api.github.com/repos/vishnu-Swagan/swag-bot. GitHub receives that request under GitHub’s own privacy policy. If the request fails, the button still links to the repository and shows no count. The site does not add an analytics identifier to the request.
      </p>
      <p>The website has no account system and does not sell personal information, because it does not collect an account profile.</p>
      <H2>The CLI</H2>
      <p>The Swag Bot CLI has no telemetry and runs locally. It does not phone home with usage data.</p>
      <p>
        If you choose a cloud model provider, including the free plans for Gemini, Groq, OpenRouter, Cerebras, and Mistral, that provider receives the prompts you send. Their terms and privacy policies govern that processing. Local runtimes — Ollama, LM Studio, Jan, llama.cpp/llamafile, and GPT4All — keep the model call on your machine.
      </p>
      <p>
        swag doctor prints whether known API key variables are set or unset. It does not print the key. The action log and run bundles redact secrets.
      </p>
      <H2>Hosting</H2>
      <p>
        The site is deployed on Vercel. Vercel’s own request logs may exist as part of hosting. This project does not add a tracking script on top of that. Questions about hosting logs can be sent to {OWNER.email}.
      </p>
      <H2>Contact and region</H2>
      <p>
        Privacy requests go to {OWNER.email}. A postal address and the governing privacy regime are {OWNER.jurisdiction} and have not been filled in. Do not assume a specific statute applies until the owner confirms it.
      </p>
    </LegalLayout>
  );
}
