"""Find a running OpenAI-compatible local model server.

These servers are free and private: the prompt stays on this machine.
Swag Bot only probes ``GET /v1/models``. It does not install the app.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from swag_bot.onboarding.detect import MIN_SUITABLE_BILLIONS, parameter_billions

# Defaults checked on 2026-09-27 against each project's docs.
LOCAL_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    (
        "LM Studio",
        "http://localhost:1234/v1",
        "https://lmstudio.ai/docs/developer/openai-compat",
    ),
    (
        "Jan",
        "http://localhost:1337/v1",
        "https://www.jan.ai/docs",
    ),
    (
        "llama.cpp",
        "http://localhost:8080/v1",
        "https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md",
    ),
    (
        "GPT4All",
        "http://localhost:4891/v1",
        "https://github.com/nomic-ai/gpt4all/wiki/Local-API-Server",
    ),
)

# llamafile uses the same OpenAI server as llama.cpp, on port 8080.
# https://github.com/mozilla-ai/llamafile
LLAMAFILE_DOCS = "https://github.com/mozilla-ai/llamafile"

Opener = Callable[[str, float], bytes | None]


@dataclass(frozen=True)
class LocalServerState:
    """One server that answered ``GET /v1/models``."""

    name: str
    base_url: str
    model_ids: list[str]


@dataclass(frozen=True)
class LocalChoice:
    """A model Swag Bot can point LiteLLM at."""

    name: str
    base_url: str
    model_id: str
    litellm_model: str
    size_known: bool


def normalize_base_url(raw: str) -> str:
    """Return ``.../v1`` with no trailing slash.

    ``http://host:1234``, ``http://host:1234/v1``, and ``.../v1/models``
    all become the base used as LiteLLM ``api_base``.
    """
    text = raw.strip().rstrip("/")
    if not text:
        raise ValueError("base URL must not be empty")
    if "://" not in text:
        text = "http://" + text
    if text.endswith("/models"):
        text = text[: -len("/models")]
    if not text.endswith("/v1"):
        text = text + "/v1"
    return text


def probe_openai_models(
    base_url: str,
    *,
    timeout: float,
    opener: Opener | None = None,
) -> list[str] | None:
    """Model ids from ``GET {base}/models``, or None when the server is down."""
    base = normalize_base_url(base_url)
    url = base + "/models"
    fetch = opener if opener is not None else _http_get
    try:
        body = fetch(url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
    if body is None:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return _ids_from_payload(payload)


def probe_local_servers(
    *,
    timeout: float,
    opener: Opener | None = None,
    extra_base: str | None = None,
) -> list[LocalServerState]:
    """Probe the known local apps, plus ``extra_base`` when config already has one."""
    endpoints: list[tuple[str, str]] = [(name, url) for name, url, _docs in LOCAL_ENDPOINTS]
    if extra_base and extra_base.strip():
        custom = normalize_base_url(extra_base)
        if all(normalize_base_url(url) != custom for _name, url in endpoints):
            endpoints.insert(0, ("custom", custom))
    found: list[LocalServerState] = []
    for name, url in endpoints:
        ids = probe_openai_models(url, timeout=timeout, opener=opener)
        if ids is None:
            continue
        found.append(LocalServerState(name=name, base_url=normalize_base_url(url), model_ids=ids))
    return found


def choose_local_model(ids: list[str]) -> tuple[str, bool] | None:
    """Pick a model id and whether its size was visible in the id.

    A size under 7B is skipped. An id with no size token is allowed.
    Returns None when every id that has a size is under 7B and none are unsized.
    """
    sized: list[tuple[float, str]] = []
    unsized: list[str] = []
    for name in ids:
        size = parameter_billions(name)
        if size is None:
            unsized.append(name)
        elif size >= MIN_SUITABLE_BILLIONS:
            sized.append((size, name))
    if sized:
        for _size, name in sized:
            if "qwen2.5" in name.lower() and parameter_billions(name) == 7:
                return name, True
        sized.sort(key=lambda item: (item[0], item[1]))
        return sized[0][1], True
    if unsized:
        return unsized[0], False
    return None


def first_usable_server(servers: list[LocalServerState]) -> LocalChoice | None:
    """First probed server that has a model this setup will use."""
    for server in servers:
        picked = choose_local_model(server.model_ids)
        if picked is None:
            continue
        model_id, known = picked
        return LocalChoice(
            name=server.name,
            base_url=server.base_url,
            model_id=model_id,
            litellm_model="openai/" + model_id,
            size_known=known,
        )
    return None


def _ids_from_payload(payload: object) -> list[str] | None:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, str) and item]
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    names: list[str] = []
    for item in data:
        if isinstance(item, str) and item:
            names.append(item)
        elif isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                names.append(model_id)
    return names


def _http_get(url: str, timeout: float) -> bytes | None:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local server URL
            return bytes(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None
