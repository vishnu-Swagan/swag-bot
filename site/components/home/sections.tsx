import { COMPARE, COMPARE_AS_OF, COMPARE_NOTES, FAQ, INTEGRATIONS, LOOP } from "@/lib/site";
import Link from "next/link";

export function HowItWorks() {
  return (
    <section id="how" className="border-t border-line">
      <div className="mx-auto w-full max-w-6xl px-4 py-20 md:px-6">
        <p className="kicker">How it works</p>
        <h2 className="h-display mt-3 max-w-2xl text-4xl sm:text-5xl">Plan. Act. Prove.</h2>
        <ol className="mt-10 grid gap-4 lg:grid-cols-3">
          {LOOP.map((stage) => (
            <li key={stage.id} className="panel p-5">
              <p className="font-mono text-xs text-faint">{stage.index}</p>
              <h3 className="mt-3 text-2xl font-semibold tracking-tight">{stage.title}</h3>
              <p className="mt-3 text-muted">{stage.lede}</p>
              <ul className="mt-4 grid gap-2 text-sm text-muted">
                {stage.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function Safety() {
  const items = [
    {
      title: "Undo ledger",
      body: "swag undo restores the latest run, including files a shell command changed. swag undo --to STEP restores the start of that step. Irreversible actions are listed and are not restored.",
    },
    {
      title: "Taint firewall",
      body: "Tool output stays data. Text inside a file or a page that tries to rewrite the task does not become an instruction.",
    },
    {
      title: "Questions, then a jury",
      body: "Irreversible actions pause. The jury blocked a fake $500 payment.",
    },
  ];
  return (
    <section id="safety" className="border-t border-line">
      <div className="mx-auto w-full max-w-6xl px-4 py-20 md:px-6">
        <p className="kicker">Safety</p>
        <h2 className="h-display mt-3 max-w-2xl text-4xl sm:text-5xl">Three stops before damage.</h2>
        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          {items.map((item) => (
            <article key={item.title} className="panel p-5">
              <h3 className="text-xl font-semibold tracking-tight">{item.title}</h3>
              <p className="mt-3 text-muted">{item.body}</p>
            </article>
          ))}
        </div>
        <p className="mt-6 text-sm text-muted">
          The repository also ships a local sandbox, an ask-risky default, and an append-only action log.{" "}
          <Link className="link" href="/docs/cli">
            CLI reference
          </Link>
          .
        </p>
      </div>
    </section>
  );
}

export function Integrations() {
  return (
    <section id="integrations" className="border-t border-line">
      <div className="mx-auto w-full max-w-6xl px-4 py-20 md:px-6">
        <p className="kicker">Plugins, MCP, clients</p>
        <h2 className="h-display mt-3 max-w-3xl text-4xl sm:text-5xl">Cowork skills. MCP. The editor you already use.</h2>
        <p className="mt-4 max-w-2xl text-muted">
          Plugins use the Claude Cowork plugin and skills format. Swag Bot connects from Claude, Cursor, VS Code, Gemini, and Claude Desktop. There is a Chrome side-panel extension. Names are text on purpose. This page does not draw anyone else’s logo.
        </p>
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {INTEGRATIONS.map((item) => (
            <li key={item.name} className="rounded-2xl border border-line px-4 py-4">
              <p className="font-medium">{item.name}</p>
              <p className="mt-1 text-sm text-muted">{item.detail}</p>
            </li>
          ))}
        </ul>
        <Link href="/docs/mcp" className="link mt-6 inline-flex font-medium">
          MCP setup
        </Link>
      </div>
    </section>
  );
}

export function Comparison() {
  return (
    <section id="compare" className="border-t border-line">
      <div className="mx-auto w-full max-w-6xl px-4 py-20 md:px-6">
        <p className="kicker">Comparison · {COMPARE_AS_OF}</p>
        <h2 className="h-display mt-3 max-w-3xl text-4xl sm:text-5xl">Where the public record differs.</h2>
        <p className="mt-4 max-w-3xl text-muted">
          Rows besides Swag Bot are drawn from a competitive report dated {COMPARE_AS_OF}. Cells say what that report could source. Empty ground is written as “not covered”, not as a flaw. Star counts are a GitHub API snapshot from that date. They are not a ranking.
        </p>
        <div className="table-wrap mt-8">
          <table className="compare">
            <caption className="sr-only">
              Swag Bot compared with other agents using sourced notes from {COMPARE_AS_OF}
            </caption>
            <thead>
              <tr>
                <th scope="col">Agent</th>
                <th scope="col">Focus</th>
                <th scope="col">License</th>
                <th scope="col">Proof of a step</th>
                <th scope="col">Undo</th>
                <th scope="col">Plugins</th>
                <th scope="col">Stars</th>
              </tr>
            </thead>
            <tbody>
              {COMPARE.map((row) => (
                <tr key={row.name}>
                  <th scope="row" className="font-medium">
                    <a className="link" href={row.href}>
                      {row.name}
                    </a>
                  </th>
                  <td>{row.focus}</td>
                  <td>{row.license}</td>
                  <td>{row.proof}</td>
                  <td>{row.undo}</td>
                  <td>{row.supply}</td>
                  <td className="font-mono tabular-nums">{row.stars}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ol className="mt-6 grid gap-2 text-sm text-muted">
          {COMPARE_NOTES.map((note) => (
            <li key={note.id}>
              {note.href ? (
                <a className="link" href={note.href}>
                  {note.text}
                </a>
              ) : (
                note.text
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function Faq() {
  return (
    <section id="faq" className="border-t border-line">
      <div className="mx-auto w-full max-w-3xl px-4 py-20 md:px-6">
        <h2 className="h-display text-4xl">Questions</h2>
        <div className="mt-8 divide-y divide-line border-y border-line">
          {FAQ.map((item) => (
            <details key={item.q} className="group py-4">
              <summary className="cursor-pointer list-none font-medium [&::-webkit-details-marker]:hidden">
                <span className="flex items-center justify-between gap-4">
                  {item.q}
                  <span aria-hidden="true" className="font-mono text-faint group-open:rotate-45">
                    +
                  </span>
                </span>
              </summary>
              <p className="mt-3 text-muted">{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

export function FinalCta() {
  return (
    <section className="border-t border-line">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-start gap-6 px-4 py-20 md:px-6">
        <h2 className="h-display max-w-3xl text-4xl sm:text-6xl">Install it. Make it show the evidence.</h2>
        <div className="flex flex-wrap gap-3">
          <Link href="/#install" className="btn btn-accent">
            Copy the install command
          </Link>
          <Link href="/docs" className="btn btn-ghost">
            Open the docs
          </Link>
        </div>
      </div>
    </section>
  );
}
