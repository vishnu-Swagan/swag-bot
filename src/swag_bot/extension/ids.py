"""Stable names for the native messaging host and the unpacked extension.

``DEV_EXTENSION_ID`` is derived from the ``key`` in
``extension/public/manifest.json``. Unpacked Chrome uses that key, so the id
does not change when the folder moves. The Chrome Web Store assigns a
different id. ``swag extension install --extension-id`` adds it.
"""

HOST_NAME = "com.swagbot.host"

# sha256 of the manifest public key, first 32 hex digits, mapped 0-9a-f to a-p.
DEV_EXTENSION_ID = "nicbjedkjajkhgbnbjknhlccicenaohe"

PROTOCOL_VERSION = 1
