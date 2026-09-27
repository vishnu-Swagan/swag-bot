# Plugin gallery

`swag gallery` installs plugins from a static JSON index. The index can be a
file on disk or any `http://` or `https://` URL, including GitHub Pages.
There is no gallery server in this repository. A hosted index, with
reputation and a separate license, is a later project.

Before the usual install prompt, the client does three things:

1. It builds a canonical bundle of the plugin and checks the SHA-256 in the
   index, when the index has one.
2. It verifies a [minisign](https://jedisct1.github.io/minisign/) signature
   over that bundle.
3. It runs a local static scan for risky patterns and for code that needs
   permissions the manifest does not declare.

Only then does it call the existing `swag plugin install` permission grant.
Approving that prompt still writes `$SWAG_HOME/grants.json`. Declining it
copies nothing.

Unsigned plugins, and plugins whose signature or digest does not verify, are
refused. The flags below override that. Every override is appended to
`$SWAG_HOME/gallery/audit.jsonl`. A clean signed install is logged there too.

| Flag | When it is required |
| --- | --- |
| `--allow-unsigned` | The index and the plugin have no signature. |
| `--allow-tampered` | The signature, digest, or index metadata does not match the files. |
| `--allow-scan` | The scanner reported a blocking finding. |
| `--trust-new-key` | This plugin name was previously installed with a different publisher key. |

The first successful signed install pins the publisher key for that plugin
name in `$SWAG_HOME/gallery/trusted-keys.json`. A later install signed by a
different key is refused until you pass `--trust-new-key`.

`swag plugin install` does not use this path. A directory you are editing
can still be installed without a signature.

## Why minisign

The signature scheme is minisign (Ed25519). Swag Bot writes the current
prehashed form: BLAKE2b-512 of the bundle, then an Ed25519 signature, with
algorithm id `ED`. `minisign -V` accepts that file. Legacy raw `Ed`
signatures still verify. The trusted comment is signed as well, so editing
the comment fails verification.

Sigstore/cosign keyless signing was not used. It needs a live round trip to
Fulcio and Rekor, and the Python client pulls a large dependency tree. A
gallery index served as a static file has to verify offline, and the base
install stays on typer, pydantic, tomli-w, and rich. Publishers who already
use the `minisign` CLI can sign the canonical bundle with it. Swag Bot does
not decrypt password-protected secret keys. `minisign -G -W` writes an
unencrypted key, and so does `swag gallery keygen`.

## Index format

`swag_gallery` must be `1`. Unknown keys are ignored. Plugin names in one
index must be unique.

```json
{
  "swag_gallery": 1,
  "name": "example",
  "plugins": [
    {
      "name": "my-plugin",
      "version": "0.1.0",
      "description": "What it adds.",
      "author": "Your Name",
      "license": "MIT",
      "keywords": ["notes"],
      "permissions": ["filesystem.read"],
      "source": {"type": "path", "path": "plugins/my-plugin"},
      "digest": {
        "algorithm": "sha256",
        "value": "64 lowercase hex characters"
      },
      "signature": {
        "scheme": "minisign",
        "public_key": "base64 line from minisign.pub",
        "file": "full .minisig file, including newlines"
      }
    }
  ]
}
```

`source.type` is one of:

| Type | Fields | Meaning |
| --- | --- | --- |
| `path` | `path` | Plugin directory. Relative paths are resolved from the index file. A remote index cannot use a relative path. |
| `github` | `repo`, optional `ref` | Clone `https://github.com/owner/repo`. |
| `git` | `url`, optional `ref` | Clone a git URL. |
| `archive` | `url` | Download a `.tar.gz` or `.zip`. Links and `..` members are rejected. |

`digest` is the SHA-256 of the canonical bundle below. `signature.scheme`
must be `minisign`. `public_key` is the single base64 line (the same value
`minisign -P` prints). `file` is the whole `.minisig` text.

If `version` or `permissions` is present, it must match `.claude-plugin/plugin.json`.
A mismatch is treated as tampering. Omit either field to skip that check.

Set the index with `--index` / `-i` or with `SWAG_GALLERY_INDEX`.

## Canonical bundle

The signed bytes are not a tar archive. They are this byte string, so two
machines produce the same digest:

1. The ASCII line `SWAG-PLUGIN-BUNDLE/1` and a newline.
2. For each file, in ascending relative POSIX path order: the path as UTF-8,
   a newline, the decimal size, a newline, and the raw file bytes.

These are omitted: `.git/`, `__pycache__/`, `.swag-gallery/`, `.DS_Store`,
and `*.pyc`. Symbolic links are rejected. The signature lives in
`.swag-gallery/` so it is not part of the bytes it signs.

`swag gallery bundle ./my-plugin -o my-plugin.bundle` writes that string.
`swag gallery sign` signs the same bytes.

## Sign a plugin

Create a key once. The secret key file is mode `0600`. Keep it off the
plugin and out of the git repository you publish.

```bash
swag gallery keygen --output ./keys
```

That writes `./keys/minisign.key` and `./keys/minisign.pub`. The public key
line is what goes in the index and what `minisign -V -P` accepts.

Sign the plugin directory. This writes `.swag-gallery/signature.minisig`,
`.swag-gallery/public.key`, and `.swag-gallery/digest.sha256`, then prints
the JSON object to paste into the index.

```bash
swag gallery sign ./my-plugin --secret-key ./keys/minisign.key
```

To sign with the official CLI instead, hash the same bytes and sign that file:

```bash
swag gallery bundle ./my-plugin -o my-plugin.bundle
minisign -S -m my-plugin.bundle -s ./keys/minisign.key -x my-plugin.bundle.minisig
```

Put the SHA-256 of `my-plugin.bundle` in `digest.value`, the base64 public
key in `signature.public_key`, and the contents of `my-plugin.bundle.minisig`
in `signature.file`. Do not sign a zip or a git archive. Verification
rebuilds the bundle from the plugin tree and checks the signature against
those bytes.

Password-encrypted minisign secret keys are refused. Remove the password
with `minisign -C -W -s minisign.key`, or sign with `minisign -S` and only
give Swag Bot the `.minisig` file and the public key.

Publish the index JSON and the plugin directories (or point `source` at
GitHub or an archive URL). Users then run:

```bash
swag gallery search notes --index https://example.com/gallery.json
swag gallery info my-plugin --index https://example.com/gallery.json
swag gallery install my-plugin --index https://example.com/gallery.json
```

`info` exits `1` when the signature is missing or invalid, or when the scan
has a blocking finding. It does not install. `install` prints the trust
panel, then the same permission question as `swag plugin install`. `--yes`
skips the question and still prints the permissions.

## Scanner

The scanner reads the same files the bundle covers. It does not execute
them. Blocking findings refuse the install unless you pass `--allow-scan`.
Warnings and info lines are printed and do not refuse.

Blocking patterns:

| Rule | What it flags |
| --- | --- |
| `shell.curl-pipe` | `curl` or `wget` piped into a shell. |
| `shell.decode-pipe` | `base64 -d` piped into a shell. |
| `obfuscation.exec-encoded` | `eval` / `exec` / `compile` next to base64, hex escapes, or similar decoding. |
| `credentials.sensitive-path` | `~/.ssh`, `id_rsa`, `.aws/credentials`, `.netrc`, `.gnupg`, `/etc/shadow`. |
| `credentials.hardcoded` | A literal token assigned to a key, secret, or password field. |
| `exfil.sink` | webhook.site, Discord webhooks, pastebin, ngrok, and similar hosts. |
| `permissions.undeclared-network` | Network calls without the `network` permission. |
| `permissions.undeclared-secrets` | Credential access without the `secrets` permission. |
| `permissions.undeclared-shell` | Shell execution without the `shell` permission. |
| `permissions.undeclared-write` | File writes without `filesystem.write`. |

`permissions.broad-combo` is a warning when the manifest declares both
`secrets` and `network`. A long base64 literal is a warning
(`obfuscation.base64-blob`). Unused high-risk permissions are info lines.

This is a filter, not a proof. A determined plugin can hide a payload in a
form these patterns do not name. The signature tells you who signed the
bytes. The scan tells you whether those bytes match a short list of known
bad shapes. The permission prompt is still the grant.

## Audit log

`$SWAG_HOME/gallery/audit.jsonl` is append-only. One JSON object per line:

```json
{
  "event": "gallery_install",
  "plugin": "my-plugin",
  "signature": "valid",
  "digest": "sha256:…",
  "blocking": [],
  "overrides": [],
  "outcome": "installed"
}
```

`signature` is `valid`, `unsigned`, or `tampered`. `outcome` is `installed`,
`refused`, or `denied` (the signature was acceptable, and the permission
prompt was declined). `overrides` lists only the flags that were required
for that install, such as `allow-unsigned` or `allow-scan`.
