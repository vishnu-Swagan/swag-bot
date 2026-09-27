import { existsSync } from "node:fs";
import path from "node:path";
import { WALKTHROUGH_NOTE } from "@/lib/content";
import { Terminal } from "./Terminal";

function demoKind(): "mp4" | "gif" | "none" {
  const dir = path.join(process.cwd(), "public", "demo");
  if (existsSync(path.join(dir, "demo.mp4"))) return "mp4";
  if (existsSync(path.join(dir, "demo.gif"))) return "gif";
  return "none";
}

export function Demo() {
  const kind = demoKind();

  return (
    <section id="demo" className="relative z-20 bg-ink px-5 py-20 md:px-8 md:py-28" aria-labelledby="demo-title">
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:items-start">
        <div className="min-w-0">
          <p className="mono text-sm text-faint">See the commands</p>
          <h2 id="demo-title" className="display mt-3 text-[clamp(2.4rem,5vw,4rem)]">
            A quickstart, typed out.
          </h2>
          <p className="mt-4 text-lg text-muted">
            This is the documented quickstart, not a recording. The frame beside it is waiting
            for a real demo.
          </p>
          <Terminal />
          <p className="mt-4 text-sm text-faint">{WALKTHROUGH_NOTE}</p>
        </div>
        <DemoSlot kind={kind} />
      </div>
    </section>
  );
}

function DemoSlot({ kind }: { kind: "mp4" | "gif" | "none" }) {
  return (
    <div className="min-w-0 rounded-[1.4rem] border border-dashed border-line bg-ink-2 p-4 md:p-6">
      <p className="mono text-sm text-faint">Recorded demo</p>
      <div className="mt-4 flex min-h-72 items-center justify-center overflow-hidden rounded-2xl bg-ink">
        {kind === "mp4" ? (
          <video className="h-full w-full" controls preload="metadata">
            <source src="/demo/demo.mp4" type="video/mp4" />
          </video>
        ) : null}
        {kind === "gif" ? (
          // The file is supplied later by the maintainer; next/image cannot size an unknown gif.
          <img src="/demo/demo.gif" alt="Recorded Swag Bot demo" className="h-full w-full object-contain" />
        ) : null}
        {kind === "none" ? (
          <div className="max-w-sm px-6 py-10 text-center">
            <p className="display text-3xl text-paper">No recording yet</p>
            <p className="mt-3 text-muted">
              Drop a file at <code className="mono text-paper">site/public/demo/demo.mp4</code> or{" "}
              <code className="mono text-paper">demo.gif</code>. This frame will play it. Nothing
              here is a stand-in for that recording.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
