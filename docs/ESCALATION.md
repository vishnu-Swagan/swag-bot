# Uncertainty escalation and the irreversible-action jury

Swag Bot can pause when a step looks uncertain, and it can refuse an irreversible action unless a small jury approves. Both are off unless you opt in. A normal `swag run` does not ask these questions and does not call extra models.

```bash
swag run --escalate "clean this up"
```

Or in `$SWAG_HOME/config.toml`:

```toml
[escalation]
enabled = true
uncertainty_threshold = 0.6
samples = 1
jury = true
jury_size = 3
judges = []
```

`--escalate` and `--no-escalate` override `enabled` for one run.

## What “uncertain” means

Each step gets a score from 0 to 1. Confidence is one minus that score. The step pauses when the score is at or above `uncertainty_threshold` (default 0.6). The pause is a specific question, not “are you sure?”. An empty answer, or end of input, stops the step. The agent does not fill in the blank.

| Signal | What it looks at | Extra model calls |
| --- | --- | --- |
| `ambiguous_goal` | The goal names two actions, or names no file, folder, or other target | none |
| `low_confidence_output` | Hedge language (“I'm not sure…”) or an explicit low `confidence:` | none |
| `self_consistency` | Repeated answers to the same question disagree | `samples` calls, and only on the first attempt. Default `samples` is 1, so this stays off |
| `verifier_disagreement` | The checker both passed and failed the step, or its reason hedges | none |
| `retries` | The step is already on attempt 2 or later | none |

Signals that have nothing to say are left out. They are not treated as zero, so a quiet signal does not dilute a loud one. With one local model and `samples = 1`, the score still moves when the goal is vague, the model hedges, the checker disagrees, or the step is being retried.

A second attempt is itself above the default threshold, so `--escalate` will ask before a retry. Raise `uncertainty_threshold` (for example to `0.75`) if you only want the louder signals.

`suggest_threshold` in `swag_bot.core.uncertainty` picks a cutoff from uncertainty scores of steps that were wrong. It is a quantile on that sample, in the spirit of KnowNo. It is not a conformal guarantee.

## The card

The question uses the same card as a tainted-action approval: a yellow panel and a two-column table. Taint shows the source and why, then asks “Allow this action?” with the default no. This card shows the step, the score, the signal names, and the question, then asks “Your answer” with the default empty. Empty means stop.

A jury rejection uses that same card, titled “Blocked by jury”, with kind, risk, summary, target, reversibility, how independent the judges were, and why. It does not ask you to override the block.

## The jury

The jury runs only for actions classified `irreversible`. `reversible` workspace edits and `compensable` actions (an external effect with a registered inverse) are not sent to it. Those three names match the undo ledger. Until that ledger is merged, `swag_bot.core.reversibility` supplies a small stub. If `swag_bot.safety.reversibility` is importable, that classifier is used instead. Tool arguments are not a label: a model cannot mark a payment as reversible by saying so.

Set `jury = false` to keep the clarifying questions and skip the panel.

Judges are chosen for independence, not for a longer list of the same model:

1. **Different providers** (`judges = ["ollama/llama3.2", "openai/gpt-4o-mini"]`). Strongest option this panel has. Shared training data can still line their errors up.
2. **Different models** from one provider. Better than copies, still correlated.
3. **Different prompts on one model.** This is the default, and it is what you get with a single local model. The prompts ask different questions (harm, intent, and whether the goal already accepted a point of no return). They are not paraphrases. They are also not independent votes. A result on correlated judges (arXiv 2605.29800) found that a panel which fails together can be worth about two votes even when it has nine members. A one-model panel is closer to one vote. The verdict says this in plain text.

PoLL (arXiv 2404.18796) is why the panel exists at all: diverse smaller judges can beat one judge. That result is why provider diversity is preferred over asking one model three times.

Every judge has to approve. A missing model, a crash, or a response that is not JSON is a rejection. The action does not run. With one local model this still works: that model is asked three times, the card explains the weak independence, and one “no” is enough to block.

`jury_size` and `samples` are capped at 5.

## Try it

Ambiguous goal, no answer (the step stops):

```bash
swag run --escalate "clean this up"
```

Irreversible jury, one local model (the default judges list):

```toml
[escalation]
enabled = true
judges = []
```

A payment or a `curl` to another host is irreversible under the stub. A `write_file` inside the workdir is reversible and skips the jury. Two providers:

```toml
[escalation]
enabled = true
judges = ["ollama/llama3.2", "openai/gpt-4o-mini"]
```

The second judge needs that provider's API key in the environment. If a judge cannot be built, it is skipped. If none can, the session model is used and the run continues.
