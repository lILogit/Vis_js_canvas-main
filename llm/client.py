import json
import os
import re

import anthropic

from llm.prompts import SYSTEM_BASE

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1000


def _strip_markdown(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _repair_truncated_json(text: str) -> dict:
    """Best-effort recovery for JSON truncated by a token limit.

    Strategy: locate the last complete top-level array element before the
    cut-off and close the document just after it, so nodes/edges parsed so
    far are returned rather than raising an error.
    """
    # Try closing with progressively more structure until json.loads succeeds
    closers = ["]}}", "]}}", "]}", "}"]
    for suffix in [
        ']},"edges":[],"causal_prompt":"","metrics":{}}',
        '],"causal_prompt":"","metrics":{}}',
        "]}",
        "}",
    ]:
        try:
            return json.loads(text + suffix)
        except json.JSONDecodeError:
            pass

    # Last resort: strip back to the last complete object in the nodes array
    # by finding the last `}` before the truncation point and closing from there
    last_obj = text.rfind("},")
    if last_obj == -1:
        last_obj = text.rfind("}")
    if last_obj != -1:
        truncated = text[: last_obj + 1]
        for suffix in [
            '],"edges":[],"causal_prompt":"","metrics":{}}',
            "]}",
            "}",
        ]:
            try:
                return json.loads(truncated + suffix)
            except json.JSONDecodeError:
                pass

    raise ValueError("Response was truncated and could not be repaired")


def call(prompt: str, system: str = None, max_tokens: int = _MAX_TOKENS) -> dict:
    """Call Claude API and return parsed JSON dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system or SYSTEM_BASE,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    cleaned = _strip_markdown(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return _repair_truncated_json(cleaned)
