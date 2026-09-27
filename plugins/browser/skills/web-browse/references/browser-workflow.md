# Browser workflow

Tools are published as `browser__<name>` (the `browser` MCP server).

| Tool | Risk | Grant | Use it for |
| --- | --- | --- | --- |
| `browser__navigate` | network | `network` | Open an http or https URL, including a new domain |
| `browser__snapshot` | read | `mcp` | Read the title, URL, and visible text of the open page |
| `browser__extract` | read | `mcp` | Read one selector, or one attribute such as `href` |
| `browser__click` | execute | `mcp` | Click a control that does not submit and does not leave the site |
| `browser__fill` | write | `mcp` | Replace an input value |
| `browser__type_text` | write | `mcp` | Type into an element. Do not include a newline |
| `browser__submit` | network | `network` | Send a form. `url` is the page or the form action |
| `browser__download` | network | `network` | Save a URL under the output directory |
| `browser__screenshot` | write | `filesystem.write` | Save a PNG. `path` is relative |

Under `ask-risky`, read tools do not prompt. Everything else does. A missing
grant is a hard deny and does not prompt. `auto` does not prompt, but a
missing grant is still denied.

Screenshots and downloads are written on the host, under
`SWAG_BROWSER_OUTPUT` or the current directory. They are not written by the
Docker sandbox. Paths cannot contain `..` or be absolute.

Only `http` and `https` URLs are opened or downloaded.
