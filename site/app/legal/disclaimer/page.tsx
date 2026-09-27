import { H2, LegalLayout } from "@/components/legal";
import { pageMeta } from "@/lib/metadata";
import { OWNER } from "@/lib/site";

export const metadata = pageMeta(
  "Disclaimer",
  "Swag Bot output can be wrong. You are responsible for approvals and actions. No warranty and no professional advice.",
  "/legal/disclaimer",
);

export default function DisclaimerPage() {
  return (
    <LegalLayout
      title="Disclaimer"
      lede="Read this before you let an agent touch anything you care about."
    >
      <H2>Output can be wrong</H2>
      <p>
        Swag Bot uses language models. Those models can state false things with a confident tone. A proof check can catch some of those claims, as when a model said “All tests passed” and the script exited 1. A check does not make the system infallible.
      </p>
      <H2>You are responsible</H2>
      <p>
        You are responsible for the goals you give it, the actions you approve, and what happens afterward. Irreversible actions are meant to pause for questions and a jury. That pause is not a substitute for your judgment. The jury blocked a fake $500 payment in one case. That is an example, not a guarantee about the next payment.
      </p>
      <H2>No warranty</H2>
      <p>
        The software is provided “as is”, without warranty of any kind, as the MIT license states. {OWNER.entity} does not warrant that a run will succeed, that a check is complete, or that a bundle is fit for a particular purpose.
      </p>
      <H2>Not professional advice</H2>
      <p>
        Nothing on this website or in the agent’s output is legal, financial, medical, security, or other professional advice. Do not treat a run as a professional opinion.
      </p>
      <H2>Third parties</H2>
      <p>
        Models and providers you choose — including Ollama, LM Studio, Jan, llama.cpp/llamafile, GPT4All, Gemini, Groq, OpenRouter, Cerebras, and Mistral — are governed by their own terms. Plugins, MCP servers, and the Chrome extension’s host environment are also outside this disclaimer’s control. Connecting them is your decision.
      </p>
      <p>Questions: {OWNER.email}. Governing-law placeholder: {OWNER.jurisdiction}.</p>
    </LegalLayout>
  );
}
