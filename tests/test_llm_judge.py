import json

import pytest
from PIL import Image

from cap_mosaic.app import llm_judge


def _fake_post(payload_capture: dict, content: str):
    def post(url, headers, body):
        payload_capture["url"] = url
        payload_capture["headers"] = headers
        payload_capture["body"] = body
        return {"choices": [{"message": {"content": content}}]}
    return post


def _img():
    return Image.new("RGB", (64, 64), (200, 40, 40))


def test_parses_strict_json_reply():
    cap = {}
    reply = json.dumps({"score": 82, "verdict": "great",
                        "tips": ["bold subject", "keep palette small"],
                        "better_subject": ""})
    r = llm_judge.qwen_judge(_img(), key="k", post=_fake_post(cap, reply))
    assert r["score"] == 82 and r["verdict"] == "great"
    assert len(r["tips"]) == 2
    # request shape: OpenAI-compatible chat with an image part + auth header
    assert cap["url"].endswith("/chat/completions")
    assert cap["headers"]["Authorization"] == "Bearer k"
    parts = cap["body"]["messages"][0]["content"]
    assert any(p.get("type") == "image_url" for p in parts)


def test_parses_json_inside_code_fence():
    reply = "Here you go:\n```json\n{\"score\": 40, \"verdict\": \"tricky\", \"tips\": [\"low contrast\"]}\n```"
    r = llm_judge.qwen_judge(_img(), key="k", post=_fake_post({}, reply))
    assert r["score"] == 40 and r["verdict"] == "tricky"


def test_actions_are_whitelisted_and_normalized():
    reply = json.dumps({
        "score": 70, "verdict": "good", "tips": ["t"],
        "actions": [
            {"set": "colors", "value": 6},            # valid
            {"set": "colors", "value": 99},           # out of range -> clamped
            {"set": "thicken", "value": True},        # valid bool
            {"set": "dither", "value": "true"},       # stringy bool -> coerced
            {"set": "size_m", "value": 3.2},          # valid float
            {"set": "preset", "value": "space"},      # valid enum
            {"set": "preset", "value": "neon"},       # bad enum -> dropped
            {"set": "rm_rf", "value": "/"},           # unknown knob -> dropped
        ],
    })
    r = llm_judge.qwen_judge(_img(), key="k", post=_fake_post({}, reply))
    got = {(a["set"], a["value"]) for a in r["actions"]}
    assert ("colors", 24) in got            # one action per knob, last wins; 99 clamped
    assert ("thicken", True) in got
    assert ("dither", True) in got          # stringy bool coerced
    assert ("size_m", 3.2) in got
    assert ("preset", "space") in got       # the invalid "neon" was dropped
    sets = [a["set"] for a in r["actions"]]
    assert "rm_rf" not in sets
    assert sets.count("colors") == 1 and sets.count("preset") == 1


def test_missing_actions_defaults_to_empty_list():
    reply = json.dumps({"score": 50, "verdict": "good", "tips": ["t"]})
    r = llm_judge.qwen_judge(_img(), key="k", post=_fake_post({}, reply))
    assert r["actions"] == []


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("QWEEN_KEY", raising=False)
    monkeypatch.setattr(llm_judge, "_ENV_FILE", "nonexistent-env-file")
    with pytest.raises(RuntimeError, match="QWEEN_KEY"):
        llm_judge.qwen_judge(_img(), post=_fake_post({}, "{}"))
