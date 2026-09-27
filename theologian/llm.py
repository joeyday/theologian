"""Thin layer over the Anthropic SDK: build requests, run them synchronously
(small runs) or through the Message Batches API (50% cheaper, bulk runs).

Requests are plain dicts of Messages API params keyed by a custom_id, so the
same request can go either way and dry runs can inspect or cost them offline.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "low"

# $ per million tokens (input, output), standard API rates; batches are half.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def client():
    import anthropic

    return anthropic.Anthropic()


def params(model: str, effort: str, system: str, user: str, schema: dict, max_tokens: int = 16000) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        # The system prompt (study definition + categories) is identical across
        # every request in a run, so it's the cache prefix.
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    }


@dataclass
class Result:
    custom_id: str
    data: dict | None  # parsed JSON output
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


def _parse_message(custom_id: str, msg) -> Result:
    u = msg.usage
    usage = dict(input_tokens=u.input_tokens + (u.cache_creation_input_tokens or 0),
                 output_tokens=u.output_tokens, cache_read_tokens=u.cache_read_input_tokens or 0)
    if msg.stop_reason == "refusal":
        detail = getattr(msg, "stop_details", None)
        return Result(custom_id, None, f"refusal: {getattr(detail, 'category', None)}", **usage)
    if msg.stop_reason == "max_tokens":
        return Result(custom_id, None, "hit max_tokens", **usage)
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        return Result(custom_id, json.loads(text), **usage)
    except json.JSONDecodeError as e:
        return Result(custom_id, None, f"bad JSON: {e}", **usage)


def run_sync(requests: dict[str, dict], progress=print) -> list[Result]:
    """One request at a time, with server-side refusal fallbacks."""
    import anthropic

    c = client()
    out = []
    for i, (cid, p) in enumerate(requests.items(), 1):
        progress(f"[{i}/{len(requests)}] {cid}")
        try:
            msg = c.beta.messages.create(**p, betas=[FALLBACK_BETA], fallbacks="default")
            out.append(_parse_message(cid, msg))
        except anthropic.BadRequestError as e:
            out.append(Result(cid, None, f"bad request: {e.message}"))
    return out


def submit_batch(requests: dict[str, dict]) -> str:
    """Submit and return the batch id. (Fallbacks aren't available on the
    Batches API; refused requests are reported and can be re-run with --sync.)"""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    batch = client().messages.batches.create(requests=[
        Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**p)) for cid, p in requests.items()
    ])
    return batch.id


def wait_batch(batch_id: str, progress=print, poll: int = 30) -> list[Result]:
    c = client()
    while True:
        b = c.messages.batches.retrieve(batch_id)
        if b.processing_status == "ended":
            break
        n = b.request_counts
        progress(f"batch {batch_id}: {n.processing} processing, {n.succeeded} done, {n.errored} errored")
        time.sleep(poll)
    out = []
    for r in c.messages.batches.results(batch_id):
        if r.result.type == "succeeded":
            out.append(_parse_message(r.custom_id, r.result.message))
        elif r.result.type == "errored":
            out.append(Result(r.custom_id, None, f"errored: {r.result.error.type}"))
        else:
            out.append(Result(r.custom_id, None, r.result.type))
    return out


def estimate_tokens(requests: dict[str, dict]) -> tuple[int, int]:
    """Rough offline (input, cached-prefix) token estimate: ~3.5 chars/token."""
    total = cached = 0
    for p in requests.values():
        sys_chars = sum(len(b["text"]) for b in p["system"])
        user_chars = sum(len(m["content"]) for m in p["messages"])
        total += int((sys_chars + user_chars) / 3.5)
        cached += int(sys_chars / 3.5)
    return total, cached


def cost(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, batch: bool = False) -> float:
    pin, pout = PRICES.get(model, PRICES[DEFAULT_MODEL])
    usd = (input_tokens * pin + cache_read * pin * 0.1 + output_tokens * pout) / 1e6
    return usd / 2 if batch else usd


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
