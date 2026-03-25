import json
import os
import re

import anthropic
from openai import OpenAI

from llm.prompts import SYSTEM_BASE

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4000

_ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"
_ZAI_MODEL = "glm-4.5-air"

_OPENAI_BASE_URL = "https://api.openai.com/v1"
_OPENAI_MODEL = "gpt-5"


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


def _active_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "anthropic").lower()


def call(prompt: str, system: str = None, max_tokens: int = _MAX_TOKENS) -> dict:
    """Call the active LLM provider and return parsed JSON dict."""
    provider = _active_provider()
    if provider == "zai":
        raw = _call_zai(prompt, system or SYSTEM_BASE, max_tokens)
    elif provider == "openai":
        raw = _call_openai(prompt, system or SYSTEM_BASE, max_tokens)
    else:
        raw = _call_anthropic(prompt, system or SYSTEM_BASE, max_tokens)
    cleaned = _strip_markdown(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return _repair_truncated_json(cleaned)


def _call_anthropic(prompt: str, system: str, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_openai(prompt: str, system: str, max_tokens: int) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set (required when LLM_PROVIDER=openai)")
    client = OpenAI(base_url=_OPENAI_BASE_URL, api_key=api_key)
    response = client.chat.completions.create(
        model=_OPENAI_MODEL,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def _call_zai(prompt: str, system: str, max_tokens: int) -> str:
    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        raise EnvironmentError("ZAI_API_KEY is not set (required when LLM_PROVIDER=zai)")
    client = OpenAI(base_url=_ZAI_BASE_URL, api_key=api_key)
    response = client.chat.completions.create(
        model=_ZAI_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content
