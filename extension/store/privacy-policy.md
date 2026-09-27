# Swag Bot Chrome extension privacy policy

This policy covers the Swag Bot Chrome extension. Swag Bot is free software
under the MIT license. The extension is a side panel for a copy of Swag Bot
that you install on your own computer.

## What the extension does

The extension sends a task you type to Swag Bot on the same computer. It can
also send the current tab's URL, title, selected text, and readable text when
you click "Use this page" or run a task with "Act in this tab" turned on. If
you allow it, Swag Bot can read, click, type, and navigate in that tab. Every
such action is decided by Swag Bot's permission policy, and the panel asks
you to approve or deny actions that are not plain reads (unless you chose
the `auto` autonomy level).

## Where data goes

The extension does not contact a server operated for this extension. It does
not use a content delivery network, analytics service, or crash reporter.
There is no account and no telemetry.

Chrome starts a native messaging host on your computer (`swag extension
install`). Task text, page text, approval answers, and tab-action results
travel only through that local connection. They are not sent to the extension
author.

Swag Bot itself may call the model you configured. That can be a program on
your computer, such as Ollama, or a model provider using an API key you set
in your environment. That call is made by Swag Bot, not by this extension.
The provider's policy applies to what you configured Swag Bot to send.

Page text and task text can be written into Swag Bot's local run files
(`plan.json`, `action-log.jsonl`, `summary.md`) and its local action log
under your `SWAG_HOME` directory (by default `~/.swag`). Those files stay on
your computer. The action log redacts common secret shapes before it stores
a line.

## What is stored in Chrome

The panel remembers your autonomy choice and whether you wanted "Act in this
tab" in the extension page's local storage. It does not sync that to a
Google account. Chrome stores the optional site-access grant if you accept
it. Removing the extension removes that extension storage.

## Permissions

- **sidePanel** shows the task, progress, and approval buttons.
- **nativeMessaging** talks to the local host. It does not open a network port.
- **activeTab** and **scripting** read or change the current tab when you ask.
- **Optional access to http and https sites** is requested only if you turn on
  "Act in this tab". You can refuse it and still send tasks and attached page
  text.

The extension does not read your browsing history, cookies, or passwords as
such. Readable page text can of course contain whatever the page shows.

## What this extension does not do

- It does not sell or share data.
- It does not load remote code.
- It does not let websites message the extension.
- It does not run when you have not opened the panel, except for the small
  service worker that tells Chrome to open the side panel when you click the
  icon.

## Contact

Questions about this policy can be sent through the project repository:
https://github.com/vishnu-Swagan/swag-bot

## Changes

This policy matches the extension in the Swag Bot repository. If the
extension starts sending data somewhere new, this file will change in that
same repository before that version is published.
