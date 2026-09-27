---
name: web-browse
description: >
  Browse a website or web page to finish a multi-step task. Use when the user
  asks to browse, open a site, click, fill a form, take a screenshot, download
  a file, or extract data from a page.
license: MIT
compatibility: >
  Requires the browser plugin MCP server (swag browser-mcp), Playwright, and
  a local Chromium. Browser actions run on the host, not inside the Docker
  sandbox. navigate, submit, and download need the network grant.
metadata:
  author: swag-bot
  version: "0.1.0"
allowed-tools: Read
---

# Browse the web

Use the browser tools for a goal that needs a live page. Read
`references/browser-workflow.md` before the first action.

Do the work in this order:

1. `browser__navigate` with the http or https URL. This is a network action.
   A host this session has not opened is a new domain and is approved on its
   own. Do not invent a URL the user did not ask for.
2. `browser__snapshot` to read the title, URL, and visible text.
3. `browser__extract` when you need one element or attribute. `browser__click`
   for controls that are not submit buttons. `browser__fill` or
   `browser__type_text` to enter text. Neither of those submits the form.
4. `browser__submit` only when the task asks to send the form. Pass `url` as
   the open page, or the form action if that host is different. This is a
   network action.
5. `browser__download` only when the task asks for a file. Pass an http or
   https URL and a relative `path`. This is a network action.
6. `browser__screenshot` when the task asks for a picture of the page. `path`
   is relative to the browser output directory.

If `browser__click` returns an error about a new domain or a form submit, call
`browser__navigate` or `browser__submit` instead of trying the click again.

Quote text you actually read from the page. Do not invent prices, titles, or
links. If an action is denied, stop and say so.
