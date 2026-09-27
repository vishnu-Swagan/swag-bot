---
name: github-issue-helper
description: >
  Draft and triage GitHub issues. Use when the user mentions GitHub issues,
  bug reports, or pull request descriptions.
license: MIT
compatibility: Requires the official GitHub MCP server. Keep the token in GITHUB_PERSONAL_ACCESS_TOKEN.
metadata:
  author: swag-bot
  version: "0.1.0"
allowed-tools: Read
---

# GitHub issue helper

When a GitHub issue or pull request needs a title and a body:

1. Read `references/issue-checklist.md` before writing.
2. Prefer the official GitHub MCP server over scraping the website.
3. Do not invent issue numbers, labels, or repository names.

Keep the result short enough to paste into GitHub.
