"use client";

import { LOOP_STAGES } from "@/lib/content";
import { motion, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";

export function LoopStory() {
  return (
    <section id="loop" className="relative z-10 px-5 md:px-8" aria-labelledby="loop-title">
      <div className="mx-auto max-w-6xl border-t border-line py-16 md:py-24">
        <p className="mono text-sm text-faint">How a run works</p>
        <h2 id="loop-title" className="display mt-3 max-w-3xl text-[clamp(2.4rem,5vw,4rem)]">
          One goal. Three moves.
        </h2>
        <p className="mt-4 max-w-xl text-lg text-muted">
          <code className="mono text-paper">swag run</code> plans the goal, carries the steps
          out, and checks its own work. Scroll through the loop.
        </p>
      </div>
      <ol className="mx-auto max-w-6xl list-none p-0">
        {LOOP_STAGES.map((stage) => (
          <Stage key={stage.id} stage={stage} />
        ))}
      </ol>
    </section>
  );
}

function StageScene({ stage }: { stage: (typeof LOOP_STAGES)[number] }) {
  return (
    <div className="flex flex-col justify-center gap-3">
      {stage.id === "do" ? <ApprovalCue /> : null}
      {stage.id === "verify" ? <OutputFiles /> : null}
      <ul className="flex flex-col gap-3">
        {stage.points.map((point) => (
          <li key={point} className="rounded-2xl border border-line bg-ink/70 px-4 py-3 text-muted">
            {point}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ApprovalCue() {
  return (
    <div className="rounded-2xl border border-coral/40 bg-ink px-4 py-3">
      <p className="mono text-xs text-coral">Approval required</p>
      <p className="mt-1 text-paper">Allow this action?</p>
      <p className="text-sm text-faint">The default answer is no.</p>
    </div>
  );
}

function OutputFiles() {
  return (
    <ul className="grid gap-2 sm:grid-cols-3">
      {["plan.json", "action-log.jsonl", "summary.md"].map((file) => (
        <li key={file} className="mono rounded-2xl border border-mint/40 bg-ink px-3 py-3 text-sm text-mint">
          {file}
        </li>
      ))}
    </ul>
  );
}

function Stage({ stage }: { stage: (typeof LOOP_STAGES)[number] }) {
  const slot = useRef<HTMLLIElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: slot,
    offset: ["start start", "end start"],
  });
  const scale = useTransform(scrollYProgress, [0, 1], [1, 0.96]);

  return (
    <li ref={slot} className="loop-slot">
      <article className={`loop-panel stage-${stage.id}`}>
        <motion.div
          style={reduce ? undefined : { scale }}
          className="loop-stage grid gap-8 rounded-[1.75rem] border border-line bg-ink-2 p-6 shadow-[0_30px_80px_rgba(0,0,0,0.28)] md:grid-cols-[0.9fr_1.1fr] md:p-10"
        >
          <div>
            <p className="mono text-sm" style={{ color: "var(--stage)" }}>
              {stage.index}
            </p>
            <h3 className="display mt-2 text-5xl md:text-6xl" style={{ color: "var(--stage)" }}>
              {stage.title}
            </h3>
            <p className="mt-4 text-lg text-paper">{stage.lede}</p>
          </div>
          <StageScene stage={stage} />
        </motion.div>
      </article>
    </li>
  );
}
