# Browser plugin

A first-party Swag Bot plugin that browses the web: open a page, read it,
click, type, fill a form, submit it, take a screenshot, download a file, and
extract text. It uses [Playwright](https://playwright.dev/python/) (Apache-2.0)
to drive headless Chromium on your machine. No browser service is contacted.

The plugin is a normal Cowork directory. Swag Bot loads the skill and starts
the MCP server declared in `.mcp.json`. That server is `swag browser-mcp`,
which speaks MCP over stdio and launches Chromium on the first browser action.

## Install

Python 3.11 or newer. From a checkout:

```bash
python -m pip install -e ".[browser]"
python -m playwright install chromium
swag plugin validate ./plugins/browser
swag plugin install ./plugins/browser
```

`swag plugin install` prints the requested permissions and asks before it
copies anything. `--yes` prints the same list and skips the question.
Approving the install writes the grants to `$SWAG_HOME/grants.json`.

`browser` is an optional extra. A normal `pip install swag-bot` does not
install Playwright. The core package stays the same size.

The same extra works from Git:

```bash
python -m pip install "swag-bot[browser] @ git+https://github.com/vishnu-Swagan/swag-bot.git"
python -m playwright install chromium
```

Install the plugin from a checkout of this repository (`./plugins/browser`).
The repository root is the Swag Bot package, not a plugin by itself. To edit
the plugin without reinstalling, add its parent to `plugin_dirs` in
`$SWAG_HOME/config.toml`. Grants still come from the install (or from
`swag safety grant`).

Chromium is a separate download (`python -m playwright install chromium`).
`swag doctor` reports whether the `playwright` module is installed. It does
not download a browser.

## Permissions

The manifest asks for three grants:

| Grant | What it allows |
| --- | --- |
| `network` | `browser__navigate`, `browser__submit`, and `browser__download` |
| `mcp` | Talk to this plugin's MCP server. Also covers reading the open page (`browser__snapshot`, `browser__extract`), clicking, typing, and filling |
| `filesystem.write` | `browser__screenshot` writes a PNG under the output directory |

`swag plugin install` shows that list. Declining writes no grants and copies
nothing. `swag plugin disable` suspends the grants. `swag plugin remove`
revokes them.

Every browser tool call goes through the permission policy in the
plan-do-verify loop, the same path as `read_file` and MCP tools.

| Action | Risk | `ask-risky` (the default) |
| --- | --- | --- |
| `browser__snapshot`, `browser__extract` | read | Allowed when the `mcp` grant is active. No prompt |
| `browser__click` | execute | Prompt |
| `browser__type_text`, `browser__fill`, `browser__screenshot` | write | Prompt |
| `browser__navigate`, `browser__submit`, `browser__download` | network | Prompt. The summary includes the URL |

`ask-always` prompts for every action, including reads. `auto` does not
prompt. A missing grant is a hard deny in every autonomy level, with no
prompt. Revoking `network` blocks navigation, form submit, and downloads
even if `mcp` remains:

```bash
swag safety revoke browser network
```

Risky actions are their own tools so the approval shows what will happen:

- **New domain.** `browser__navigate` is a network action and the prompt
  includes the URL. A click on a link whose host this session has not opened
  is refused. The tool result tells the agent to call `browser__navigate`
  with that URL, which is approved on its own. `www.example.com` and
  `example.com` count as the same host.
- **Submit.** Clicking a submit button is refused. `browser__submit` is the
  network action. Pass `url` as the open page, or as the form action when
  that host is different. If the form posts somewhere else, the tool returns
  the destination and does not send the form until `url` names that host.
- **Download.** Only `browser__download` fetches a file. Clicks do not accept
  downloads. The file must be http or https, at most 20 MB, and the path
  stays inside the output directory.

`javascript:`, `data:`, and `file:` URLs are rejected.

## Example

```bash
swag run "Open https://example.com and tell me the heading"
```

With the default autonomy, `ask-risky`, Swag Bot asks before
`browser__navigate` and then reads the page with `browser__snapshot`. A
multi-step task uses the `web-browse` skill, which the selector picks up
when the goal mentions browsing, a website, a form, a screenshot, or
extracting data:

```bash
swag run "Open https://example.com, extract the heading, and save a screenshot as example.png"
```

Screenshots and downloads go to `SWAG_BROWSER_OUTPUT`, or the current
directory when that variable is unset. The plugin's `.mcp.json` passes the
variable through, with `.` as the default.

```bash
export SWAG_BROWSER_OUTPUT="$PWD/swag-output"
swag run "Open https://example.com and save a screenshot as example.png" \
  --output-dir "$PWD/swag-output"
```

Set `SWAG_BROWSER_HEADED=1` to show the window. The default is headless.
`SWAG_BROWSER_TIMEOUT` is the navigation timeout in seconds (default 20).

## Sandbox

The browser does **not** run inside the Docker sandbox.

The Docker sandbox is a throwaway container: network off unless you turn it
on, a read-only root filesystem, and a slim Python image. Chromium needs a
network stack, shared memory, and system libraries that image does not have.
Putting the browser in that container would mean enabling the network and
replacing the image, which weakens the sandbox for every shell command in
the same run.

`swag browser-mcp` is a child process of `swag run` on the host. File and
shell tools still use the sandbox. Browser screenshots and downloads are
files on the host, under `SWAG_BROWSER_OUTPUT`. The permission policy still
runs before every browser tool call, and a missing grant is still a hard
deny. The local sandbox is a subprocess jail for shell commands; it does not
wrap MCP servers, so the same host-process trade-off applies when
`sandbox.mode` is `local`.

The browser can reach any host the machine can reach. That is why
`browser__navigate`, `browser__submit`, and `browser__download` are network
actions and require the `network` grant.

## Tools

See `skills/web-browse/references/browser-workflow.md` for the table the
agent reads. The implementation lives in `src/swag_bot/browser/`. Tests that
do not need Chromium are in `tests/browser/`. `test_integration.py` launches
headless Chromium and is skipped when Playwright or the browser is not
installed.
