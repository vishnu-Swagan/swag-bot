# Chrome Web Store listing draft

Upload `extension/store/dist/swag-bot-0.1.0.zip` from `npm run package` inside
`extension/`. That zip strips the `key` field. The store assigns the
extension id. After it is published, users register that id with:

```bash
swag extension install --extension-id <id from chrome://extensions>
```

Host `privacy-policy.md` on the project site and put that URL in the store's
privacy-policy field. This draft does not invent a URL, a user count, or a
rating.

## Name

Swag Bot

## Short description

Give tasks to Swag Bot on your computer. Watch the plan, approve actions, and share the current page.

(101 characters. The store limit is 132.)

## Detailed description

Swag Bot is a free, MIT-licensed agent that runs on your computer. This
extension is the Chrome side panel for that agent.

You write a task. The panel shows the plan as Swag Bot works through it, and
it asks you to approve or deny actions. You can attach the current tab's URL,
title, selected text, and readable text. If you turn on "Act in this tab" and
allow site access, Swag Bot can also read, click, type, and navigate in that
tab. Those actions use the same permission policy as the `swag` command:
reads can proceed, and clicks, typing, and navigation ask first under the
default autonomy level.

The extension does not talk to a Swag Bot server. Chrome starts a local
native messaging host (`swag extension install`) and the messages stay on
your machine. The model Swag Bot calls is the one you already configured,
such as Ollama on localhost or a provider key in your environment.

Setup:

1. Install Swag Bot and confirm `swag version` works.
2. Run `swag extension install --extension-id <the id on chrome://extensions>`.
3. Quit Chrome completely, then open it again.
4. Click the Swag Bot icon.

Source: https://github.com/vishnu-Swagan/swag-bot

## Category

Productivity

## Language

English

## Single-purpose statement

This extension's single purpose is to let a person send tasks to the Swag Bot
agent installed on their own computer, watch that agent's plan-do-verify
progress, approve or deny its actions, and optionally share or control the
current browser tab.

## Permission justifications

| Permission | Why it is requested |
| --- | --- |
| `sidePanel` | The product is a side panel: the task, the live plan, and the approve/deny buttons live there. |
| `nativeMessaging` | The extension cannot start a process. This is the channel to the local `swag` host. No remote server is contacted. |
| `activeTab` | "Use this page" reads the URL, title, selection, and text of the tab the person is using, after they invoke the extension. |
| `scripting` | The same button injects a short reader into that tab. Tab actions (click, type, fill, submit, extract) use the same API, only after Swag Bot's permission policy allows them. |
| Optional host permissions `http://*/*` and `https://*/*` | Not granted at install. Requested only when the person turns on "Act in this tab", so the agent can keep acting in the tab after a navigation. The Chrome prompt is shown at that moment. |

The extension does not request `<all_urls>`, `tabs`, `history`, `cookies`,
`webRequest`, or remote code. It has no externally connectable sites and no
web-accessible resources.

## Screenshots

1280×800 PNGs of the extension running, in `extension/store/screenshots/`:

- `01-task.png` — connected panel with a task and the current page attached
- `02-progress.png` — plan-do-verify steps updating
- `03-approval.png` — approve and deny for a navigation

## Icons

`extension/public/icons/icon16.png`, `icon32.png`, `icon48.png`, `icon128.png`.
