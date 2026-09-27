import { CLOUD_MODELS, LOCAL_MODELS } from "@/lib/site";

const MODELS = [
  ...LOCAL_MODELS.map((item) => ({ ...item, local: true })),
  ...CLOUD_MODELS.map((item) => ({ ...item, local: false })),
];

const rules = MODELS.map(
  (item) => `.model-picker:has(#model-${item.id}:checked) [data-model="${item.id}"]{display:block}
.model-picker:has(#model-${item.id}:checked) label[for="model-${item.id}"]{border-color:var(--text);background:var(--text);color:var(--bg)}`,
).join("");

export function ModelPicker() {
  return (
    <section id="models" className="border-t border-line">
      <div className="mx-auto grid w-full max-w-6xl gap-8 px-4 py-20 md:px-6 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <p className="kicker">Runs on your hardware</p>
          <h2 className="h-display mt-3 text-4xl sm:text-5xl">Local by default. Cloud when you ask.</h2>
          <p className="mt-4 text-muted">
            Pick a runtime. Local models stay on your machine. A free cloud plan receives the prompts you choose to send, under that provider’s terms.
          </p>
        </div>
        <div className="model-picker">
          <style>{`.model-stage article{display:none}${rules}`}</style>
          <div role="radiogroup" aria-label="Model runtimes" className="flex flex-wrap gap-2">
            {MODELS.map((item, index) => (
              <div key={item.id} className="inline-flex">
                <input
                  className="sr-only"
                  type="radio"
                  name="model"
                  id={`model-${item.id}`}
                  defaultChecked={index === 0}
                />
                <label htmlFor={`model-${item.id}`} className="model-pill">
                  {item.name}
                </label>
              </div>
            ))}
          </div>
          <div className="model-stage">
            {MODELS.map((item) => (
              <article key={item.id} data-model={item.id} className="panel mt-4 p-5">
                <p className="kicker">{item.local ? "Local" : "Free cloud plan"}</p>
                <h3 className="mt-2 text-xl font-semibold">{item.name}</h3>
                <p className="mt-3 text-muted">{item.note}</p>
                {item.command ? (
                  <code className="mt-4 block overflow-x-auto font-mono text-sm">{item.command}</code>
                ) : (
                  <p className="mt-4 text-sm text-faint">
                    No extra command is invented here. Point Swag Bot at that runtime the way its docs describe, then confirm with{" "}
                    <span className="font-mono">swag doctor</span>.
                  </p>
                )}
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
