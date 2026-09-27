import { FeatureMotion } from "@/components/home/feature-motion";
import { MicroDemo } from "@/components/home/micro-demos";
import { FEATURES } from "@/lib/site";
import Link from "next/link";

const rules = FEATURES.map(
  (feature) => `
.feature-picker:has(#feature-${feature.slug}:checked) [data-feature="${feature.slug}"]{display:flex}
.feature-picker:has(#feature-${feature.slug}:checked) label[for="feature-${feature.slug}"]{border-color:var(--line-strong);background:var(--elev)}
`,
).join("");

export function FeatureBento() {
  return (
    <section id="features" className="mx-auto w-full max-w-6xl px-4 py-20 md:px-6">
      <div className="max-w-2xl">
        <p className="kicker">v0.2 · ten capabilities</p>
        <h2 className="h-display mt-3 text-4xl sm:text-5xl">What the run has to show.</h2>
        <p className="mt-4 text-muted">
          Select a capability. The panel is the same fact the rest of the page uses. Nothing here is a testimonial or a user count.
        </p>
      </div>
      <div id="feature-picker" className="feature-picker mt-8">
        <style>{`.feature-stage article{display:none}${rules}`}</style>
        <div role="radiogroup" aria-label="Ten features" className="grid gap-3 sm:grid-cols-2">
          {FEATURES.map((item, index) => (
            <div key={item.slug}>
              <input
                className="sr-only"
                type="radio"
                name="feature"
                id={`feature-${item.slug}`}
                defaultChecked={index === 0}
              />
              <label htmlFor={`feature-${item.slug}`} className="feature-label">
                <span className="font-mono text-xs text-faint">{item.index}</span>
                <span className="mt-2 block font-medium">{item.title}</span>
              </label>
            </div>
          ))}
        </div>
        <div className="feature-stage">
          {FEATURES.map((feature) => (
            <article key={feature.slug} data-feature={feature.slug} className="panel flex-col p-5">
              <p className="kicker">Feature {feature.index}</p>
              <h3 className="mt-3 text-2xl font-semibold tracking-tight">{feature.title}</h3>
              <p className="mt-3 text-muted">{feature.summary}</p>
              <div className="mt-5 rounded-xl border border-line bg-bg p-4">
                <MicroDemo kind={feature.demo} />
              </div>
              <p className="mt-4 text-sm text-muted">{feature.fact}</p>
              <Link href={`/features/${feature.slug}`} className="link mt-5 inline-flex font-medium">
                Read {feature.title}
              </Link>
            </article>
          ))}
        </div>
        <FeatureMotion />
      </div>
    </section>
  );
}
