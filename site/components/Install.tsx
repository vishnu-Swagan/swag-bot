"use client";

import {
  EXTRA_COMMANDS,
  FIRST_RUN_COMMAND,
  INSTALL_COMMAND,
  MODEL_SET_COMMAND,
  MODELS_DOC_URL,
  OLLAMA_COMMANDS,
  OLLAMA_URL,
  PIP_PIN_COMMAND,
  PIPX_COMMAND,
} from "@/lib/content";
import { useRef, useState, type KeyboardEvent } from "react";
import { CopyButton } from "./CopyButton";
import { Outbound } from "./Outbound";

const TABS = [
  { id: "install", label: "Install" },
  { id: "ollama", label: "Ollama" },
  { id: "run", label: "First run" },
] as const;

export function Install() {
  const [active, setActive] = useState(0);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "ArrowRight"
        ? (active + 1) % TABS.length
        : event.key === "ArrowLeft"
          ? (active - 1 + TABS.length) % TABS.length
          : event.key === "Home"
            ? 0
            : TABS.length - 1;
    setActive(next);
    tabs.current[next]?.focus();
  }

  return (
    <section id="install" className="relative z-20 bg-ink px-5 py-20 md:px-8 md:py-28" aria-labelledby="install-title">
      <div className="mx-auto max-w-6xl">
        <p className="mono text-sm text-faint">Get started</p>
        <h2 id="install-title" className="display mt-3 max-w-3xl text-[clamp(2.4rem,5vw,4rem)]">
          Install it, point it at Ollama, run a goal.
        </h2>
        <div className="mt-8 overflow-hidden rounded-[1.6rem] border border-line bg-ink-2">
          <div
            className="flex gap-2 overflow-x-auto border-b border-line p-3"
            role="tablist"
            aria-label="Install steps"
            onKeyDown={onKeyDown}
          >
            {TABS.map((tab, index) => (
              <button
                key={tab.id}
                ref={(node) => {
                  tabs.current[index] = node;
                }}
                id={`tab-${tab.id}`}
                type="button"
                role="tab"
                className={`btn min-h-11 px-4 ${index === active ? "btn-lime" : "btn-ghost"}`}
                aria-selected={index === active}
                aria-controls={`panel-${tab.id}`}
                tabIndex={index === active ? 0 : -1}
                onClick={() => setActive(index)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="p-5 md:p-8">
            {active === 0 ? <InstallPanel /> : null}
            {active === 1 ? <OllamaPanel /> : null}
            {active === 2 ? <RunPanel /> : null}
          </div>
        </div>
      </div>
    </section>
  );
}

function CommandBlock({ command, label }: { command: string; label: string }) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-ink px-4 py-3">
      <pre className="mono m-0 min-w-0 flex-1 overflow-x-auto text-sm leading-6 text-paper">
        <code>{command}</code>
      </pre>
      <CopyButton value={command} label={label} className="btn btn-ghost min-h-11 px-4" />
    </div>
  );
}

function InstallPanel() {
  return (
    <div role="tabpanel" id="panel-install" aria-labelledby="tab-install">
      <h3 className="display text-3xl">Install the package</h3>
      <p className="mt-3 max-w-2xl text-muted">
        Python 3.11 or newer. PyPI publishing is opt-in, so install from Git for now. When
        publishing is on, the command below becomes <code className="mono text-paper">pip install swag-bot</code>.
      </p>
      <CommandBlock command={INSTALL_COMMAND} label="Copy" />
      <details className="mt-6">
        <summary className="cursor-pointer text-paper">Other install forms from the docs</summary>
        <div className="mt-4 space-y-4 text-muted">
          <p>The README’s pinned pip install, which names the package:</p>
          <CommandBlock command={PIP_PIN_COMMAND} label="Copy" />
          <p>With pipx, so the <code className="mono text-paper">swag</code> command stays isolated. The tag pins v0.1.0.</p>
          <CommandBlock command={PIPX_COMMAND} label="Copy" />
          <p>Optional extras. The README says to add <code className="mono text-paper">@v0.1.0</code> to pin the release.</p>
          {EXTRA_COMMANDS.map((extra) => (
            <div key={extra.name}>
              <p>
                <code className="mono text-paper">{extra.name}</code> — {extra.detail}
              </p>
              <CommandBlock command={extra.command} label="Copy" />
            </div>
          ))}
          <p>
            A checkout for development is <code className="mono text-paper">python -m pip install -e &quot;.[dev]&quot;</code>.
            Swag Bot does not read a <code className="mono text-paper">.env</code> file. Export keys yourself.{" "}
            <code className="mono text-paper">swag doctor</code> prints set or unset, and never the value.
          </p>
        </div>
      </details>
    </div>
  );
}

function OllamaPanel() {
  return (
    <div role="tabpanel" id="panel-ollama" aria-labelledby="tab-ollama">
      <h3 className="display text-3xl">Set up Ollama</h3>
      <p className="mt-3 max-w-2xl text-muted">
        Install <Outbound href={OLLAMA_URL} className="text-paper underline decoration-lime/70 underline-offset-4">Ollama</Outbound>, then pull a model. The default config is provider <code className="mono text-paper">ollama</code> and model <code className="mono text-paper">llama3.2</code>. The client talks to <code className="mono text-paper">http://127.0.0.1:11434</code> unless <code className="mono text-paper">OLLAMA_HOST</code> or <code className="mono text-paper">model.api_base</code> says otherwise. No API key is sent.
      </p>
      <CommandBlock command={OLLAMA_COMMANDS} label="Copy" />
      <p className="mt-6 text-muted">
        To pin that in <code className="mono text-paper">$SWAG_HOME/config.toml</code> (default directory <code className="mono text-paper">~/.swag</code>):
      </p>
      <CommandBlock command={MODEL_SET_COMMAND} label="Copy" />
      <p className="mt-6 text-muted">
        A missing config file is fine. <code className="mono text-paper">swag doctor</code> prints the config that would be used. For a cloud model, see the{" "}
        <Outbound href={MODELS_DOC_URL} className="text-paper underline decoration-lime/70 underline-offset-4">
          models doc
        </Outbound>
        . Keys stay in the environment. They are not written to config.
      </p>
    </div>
  );
}

function RunPanel() {
  return (
    <div role="tabpanel" id="panel-run" aria-labelledby="tab-run">
      <h3 className="display text-3xl">First swag run</h3>
      <p className="mt-3 max-w-2xl text-muted">
        This example uses <code className="mono text-paper">--autonomy auto</code>, so it does not ask. The default is <code className="mono text-paper">ask-risky</code>. Actions are still logged. A hard deny still applies.
      </p>
      <CommandBlock command={FIRST_RUN_COMMAND} label="Copy" />
      <p className="mt-6 text-muted">The output directory receives:</p>
      <ul className="mt-3 grid gap-2 sm:grid-cols-3">
        {["plan.json", "action-log.jsonl", "summary.md"].map((file) => (
          <li key={file} className="mono rounded-2xl border border-line px-4 py-3 text-paper">
            {file}
          </li>
        ))}
      </ul>
      <p className="mt-6 text-muted">
        Other flags: <code className="mono text-paper">--dry-run</code>,{" "}
        <code className="mono text-paper">--max-steps</code>,{" "}
        <code className="mono text-paper">--max-attempts</code>,{" "}
        <code className="mono text-paper">--concurrency</code>,{" "}
        <code className="mono text-paper">--model</code>, and{" "}
        <code className="mono text-paper">--engine</code> (<code className="mono text-paper">python</code> or{" "}
        <code className="mono text-paper">graphbit</code>). The default scheduler is pure Python. GraphBit is optional. If it is not installed, <code className="mono text-paper">--engine graphbit</code> falls back and says so.
      </p>
    </div>
  );
}
