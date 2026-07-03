"""LLM-as-judge for cap-art suitability (Qwen vision via DashScope).

The heuristic judge (`core.critique`) is fast and deterministic but has no
taste — e.g. it punishes a halftone background as "busy". This sends the image
to `qwen3-vl-plus` (Alibaba DashScope, OpenAI-compatible endpoint, ~$0.005 per
call — same vendor pattern as olga_movie's judges) with a cap-art rubric and
returns a score/verdict/tips JSON. Network I/O is injected (``post``) so tests
run offline; the key comes from the ``QWEEN_KEY`` env var or the repo ``.env``.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Callable

from PIL import Image

QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3-vl-plus"
_ENV_FILE = ".env"

_RUBRIC = (
    "You judge images for BOTTLE-CAP MOSAIC art. Each cap is one fat pixel "
    "(~32 mm); a piece is typically 40-100 caps across, seen from metres away. "
    "Good subjects: bold silhouette, high contrast, few colours (4-8 families), "
    "simple background, iconic/recognizable at low resolution. Bad: fine detail, "
    "low contrast, busy background, many similar shades, small faces.\n"
    "You may also recommend machine-applicable settings via \"actions\": "
    "{\"set\": \"colors\", \"value\": 4-24 int (palette size — fewer for bolder "
    "art)}, {\"set\": \"thicken\", \"value\": bool (widen ~1-cap-thin lines)}, "
    "{\"set\": \"dither\", \"value\": bool (blend gradients from few colours)}, "
    "{\"set\": \"size_m\", \"value\": physical width in metres 0.2-12 (bigger = "
    "more caps = more detail)}, {\"set\": \"preset\", \"value\": one of "
    "\"portrait\"|\"sunset\"|\"space\"|\"\" (curated palette; \"\" = auto)}.\n"
    "Reply with ONLY strict JSON: {\"score\": 0-100, \"verdict\": one of "
    "\"great\"|\"good\"|\"tricky\"|\"poor\", \"tips\": [2-4 short actionable "
    "strings for THIS image], \"better_subject\": one short suggestion or \"\", "
    "\"actions\": [0-5 of the settings above that would improve THIS image]}."
)

# The judge may only touch knobs we own — everything else is dropped.
_KNOBS = {
    "colors": ("int", 4, 24),
    "thicken": ("bool", None, None),
    "dither": ("bool", None, None),
    "size_m": ("float", 0.2, 12.0),
    "preset": ("enum", ("", "portrait", "sunset", "space"), None),
}


def _clean_actions(raw) -> list[dict]:
    """Validate LLM-proposed actions against the knob whitelist (one per knob)."""
    out: dict[str, dict] = {}
    for a in raw if isinstance(raw, list) else []:
        knob = a.get("set") if isinstance(a, dict) else None
        if knob not in _KNOBS:
            continue
        kind, lo, hi = _KNOBS[knob]
        v = a.get("value")
        try:
            if kind == "int":
                v = max(lo, min(hi, int(v)))
            elif kind == "float":
                v = max(lo, min(hi, float(v)))
            elif kind == "bool":
                v = v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes")
            elif kind == "enum":
                if v not in lo:
                    continue
        except (TypeError, ValueError):
            continue
        out[knob] = {"set": knob, "value": v}  # last valid one per knob wins
    return list(out.values())


def _load_key() -> str:
    key = os.environ.get("QWEEN_KEY")
    if not key and os.path.exists(_ENV_FILE):
        for line in open(_ENV_FILE, encoding="utf-8", errors="ignore"):
            m = re.match(r"\s*QWEEN_KEY\s*=\s*(.+)", line)
            if m:
                key = m.group(1).strip().strip('"').strip("'")
                break
    if not key:
        raise RuntimeError("QWEEN_KEY not set (env var or .env) — needed for the AI judge")
    return key


def _default_post(url: str, headers: dict, body: dict) -> dict:
    import urllib.request

    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in LLM reply: {text[:200]}")
    return json.loads(m.group(0))


def qwen_judge(
    image: Image.Image,
    key: str | None = None,
    model: str = MODEL,
    post: Callable[[str, dict, dict], dict] = _default_post,
) -> dict:
    """Score `image` as a cap-art subject via Qwen VL. Returns the rubric JSON."""
    key = key or _load_key()
    im = image.convert("RGB")
    im.thumbnail((512, 512))  # plenty for judging; keeps the request small
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()

    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": _RUBRIC},
            ],
        }],
    }
    resp = post(f"{QWEN_BASE_URL}/chat/completions",
                {"Authorization": f"Bearer {key}"}, body)
    text = resp["choices"][0]["message"]["content"]
    out = _extract_json(text)
    out.setdefault("tips", [])
    out.setdefault("better_subject", "")
    out["actions"] = _clean_actions(out.get("actions"))
    out["model"] = model
    return out
