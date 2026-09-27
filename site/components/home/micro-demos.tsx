import type { DemoKind } from "@/lib/site";

export function MicroDemo({ kind }: { kind: DemoKind }) {
  if (kind === "evidence") {
    return (
      <div className="grid gap-2 font-mono text-xs">
        <Row label="claim" value='"All tests passed"' />
        <Row label="ev_91c2" value="exit 1" tone="bad" />
        <Row label="verdict" value="fail · not done" tone="bad" />
      </div>
    );
  }
  if (kind === "handoff") {
    return (
      <ol className="grid gap-2 font-mono text-xs">
        <li className="text-good">1 write notes.md · pass · ev_11</li>
        <li className="text-text">2 read notes.md · received ev_11</li>
        <li className="text-bad">3 publish · check failed · stopped</li>
      </ol>
    );
  }
  if (kind === "install") {
    return <p className="font-mono text-xs leading-5">curl …/scripts/install.sh | sh</p>;
  }
  if (kind === "harness") {
    return (
      <div className="grid gap-2 font-mono text-xs">
        <p>qwen2.5:3b · CPU · 1 step</p>
        <p className="text-good">with harness · 78s · printed 55</p>
        <p className="text-faint">without harness · still failing at ~4 min</p>
      </div>
    );
  }
  if (kind === "undo") {
    return (
      <ol className="grid gap-1 font-mono text-xs">
        <li>ledger · write report.md</li>
        <li>ledger · run_shell</li>
        <li className="text-accent-text">undo · restore both</li>
      </ol>
    );
  }
  if (kind === "sign") {
    return (
      <div className="grid gap-1 font-mono text-xs">
        <p>minisign · signature ok</p>
        <p>scanner · clean</p>
        <p className="text-faint">gallery listing · coming soon</p>
      </div>
    );
  }
  if (kind === "taint") {
    return (
      <div className="grid gap-1 font-mono text-xs">
        <p className="text-bad">tool output · “ignore the task”</p>
        <p className="text-good">firewall · tainted · not an instruction</p>
      </div>
    );
  }
  if (kind === "skill") {
    return (
      <div className="grid gap-1 font-mono text-xs">
        <p>evidence · present</p>
        <p>replay · passed</p>
        <p className="text-good">skill · kept</p>
      </div>
    );
  }
  if (kind === "jury") {
    return (
      <div className="grid gap-1 font-mono text-xs">
        <p>action · pay $500 · irreversible</p>
        <p>questions · asked</p>
        <p className="text-bad">jury · blocked</p>
      </div>
    );
  }
  return (
    <ul className="grid gap-1 font-mono text-xs">
      <li>run bundle</li>
      <li>secrets · redacted</li>
      <li className="text-good">replay · offline</li>
    </ul>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "bad" }) {
  return (
    <p className={tone === "bad" ? "text-bad" : "text-text"}>
      <span className="text-faint">{label} </span>
      {value}
    </p>
  );
}
