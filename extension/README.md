# Swag Bot for Chrome

Side panel for a Swag Bot install on the same computer. You give it a task,
watch the plan-do-verify stream, and approve or deny actions. "Use this page"
attaches the current tab's URL, title, selection, and readable text. "Act in
this tab" lets Swag Bot read, click, type, and navigate there. Those actions
use Swag Bot's permission policy. The tool names and risk levels match the
headless browser plugin (`browser__navigate`, `browser__snapshot`,
`browser__click`, `browser__type_text`, `browser__fill`, `browser__submit`,
`browser__extract`). Screenshot and download stay on that plugin.

The extension does not phone home. Chrome native messaging is the bridge:
`swag extension install` writes a host manifest, and Chrome starts the host
when this panel connects. A website cannot open that channel. See
`src/swag_bot/extension/README.md` for why this is not a localhost server.

## Develop

```bash
cd extension
npm install
npm run lint
npm run build
```

Load `extension/dist` as an unpacked extension. The manifest `key` pins the
unpacked id at `nicbjedkjajkhgbnbjknhlccicenaohe`.

```bash
swag extension install
```

Quit Chrome completely so it reads the new host manifest, then click the
toolbar icon. That click opens the side panel and lets "Use this page" read
the tab. Chrome grants that temporary access only when the action listener
runs, and it remembers `openPanelOnActionClick`, which swallows the click.
The background worker turns that behavior off and opens the panel itself.

`npm run package` writes `extension/store/dist/swag-bot-0.1.0.zip` with the
`key` field removed for the Chrome Web Store. The published id will differ.
Register it:

```bash
swag extension install --extension-id <id from chrome://extensions>
```

Store copy, the privacy policy, and icons are in `extension/store/` and
`extension/public/icons/`.

## Permissions

Required: `sidePanel`, `nativeMessaging`, `activeTab`, `scripting`.

Optional, and only after you turn on "Act in this tab": `http://*/*` and
`https://*/*`. The extension does not request `<all_urls>`.
