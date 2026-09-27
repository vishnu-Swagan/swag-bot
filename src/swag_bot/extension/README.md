# extension

Chrome side panel for Swag Bot. This package is the native messaging host.
The extension itself lives in the repository `extension/` directory and is
not imported by the agent loop.

## Why native messaging

The extension cannot start a process. A localhost server would be reachable
by other programs on the machine, and a sloppy origin check would let a
website drive it. Native messaging has neither problem:

- Chrome starts `swag-bot-host` when the side panel connects and stops it
  when the port closes. Nothing listens.
- The host manifest `allowed_origins` lists extension ids. Chrome drops
  messages from every other caller before this process sees them.

`swag extension install` writes that manifest for Chrome, Chromium, and Edge
at the user level (no administrator). On Linux and macOS the host is a shell
script that runs `python -m swag_bot.extension.host`. On Windows it is a
`.bat` file with the same command. Stdout is the framed protocol. Logs stay
on stderr.

The unpacked extension id is pinned by the `key` in
`extension/public/manifest.json` and is always allowed. After a Chrome Web
Store publish, add the store id:

```bash
swag extension install --extension-id <id from chrome://extensions>
```

Quit the browser completely afterwards. Chrome reads native host manifests
at startup.

## What a task does

The side panel sends the goal, the autonomy level, optional page text, and
whether the agent may act in the tab. This module calls `execute_goal` with
a prompter that blocks on the panel, a policy wrapper that labels
`browser__*` tools the same way as the headless browser plugin, and those
tools registered only when the person opted in.

Page text is placed in a `page-data` block and described as untrusted. Tab
actions still go through `StepExecutor`: classify, maybe prompt, then the
extension performs the click or navigation. A hard deny is unchanged.

Screenshot and download are not offered here. They belong to the headless
browser plugin. The names and risks of the shared tools match that plugin:

| Tool | Risk |
| --- | --- |
| `browser__snapshot`, `browser__extract` | read |
| `browser__type_text`, `browser__fill` | write |
| `browser__click` | execute |
| `browser__navigate`, `browser__submit` | network |

`SWAG_EXTENSION_FIXTURE=1` skips the model and emits a short scripted plan
that still uses the real approval prompt. It is for store screenshots. The
panel cannot turn it on.
