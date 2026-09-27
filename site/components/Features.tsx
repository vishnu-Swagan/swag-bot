import { FEATURES } from "@/lib/content";
import { Outbound } from "./Outbound";

export function Features() {
  return (
    <section id="features" className="relative z-20 bg-ink px-5 py-20 md:px-8 md:py-28" aria-labelledby="features-title">
      <div className="mx-auto max-w-6xl">
        <p className="mono text-sm text-faint">What you actually get</p>
        <h2 id="features-title" className="display mt-3 max-w-3xl text-[clamp(2.4rem,5vw,4rem)]">
          Local by default. Yours to extend.
        </h2>
        <p className="mt-4 max-w-2xl text-lg text-muted">
          v0.1.0 is the first release. These are the pieces that ship with it.
        </p>
        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {FEATURES.map((feature, index) => (
            <article
              key={feature.id}
              className={`rounded-[1.5rem] border border-line bg-ink-2 p-6 md:p-8 ${
                index === 0 ? "md:col-span-2" : ""
              }`}
            >
              <p className="mono text-sm text-lime">{feature.kicker}</p>
              <h3 className="display mt-2 text-3xl md:text-4xl">{feature.title}</h3>
              <p className="mt-3 max-w-3xl text-muted">{feature.body}</p>
              <dl className="mt-6 grid gap-3 sm:grid-cols-3">
                {feature.facts.map((fact) => (
                  <div key={fact.label} className="rounded-2xl border border-line px-4 py-3">
                    <dt className="mono text-xs tracking-wide text-faint uppercase">{fact.label}</dt>
                    <dd className="mt-1 text-paper">{fact.value}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-5">
                <Outbound
                  href={feature.href}
                  className="text-paper underline decoration-lime/70 underline-offset-4"
                >
                  {feature.linkLabel}
                </Outbound>
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
