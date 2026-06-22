"""Provider-agnostic chat wrapper (Anthropic + OpenAI).

A single entry point hides provider differences so the rest of the code (agents,
orchestration, reflection) never imports a vendor SDK directly. Two calls:

  - chat()      → free-text completion
  - chat_json() → structured output: instructs the model to return JSON and
                  parses it leniently. JSON-via-prompt is provider-agnostic and
                  model-agnostic (no reliance on a vendor's structured-output
                  feature), which keeps Trigger A (§7) easy to defend in the thesis.

Keys resolve from the model row (entered in Admin → Models) first, then the
environment (.env). Sampling params are deliberately NOT sent: recent Anthropic
models reject `temperature`, so omitting it keeps the wrapper model-agnostic.
"""
from __future__ import annotations

import json
import os
import re

import config

DEFAULT_MAX_TOKENS = 4096


class LLMError(RuntimeError):
    """Raised for any configuration or provider error (shown to the user)."""


def _resolve_key(provider: str, api_key: str | None) -> str | None:
    if api_key:
        return api_key
    env_var = {
        config.PROVIDER_ANTHROPIC: "ANTHROPIC_API_KEY",
        config.PROVIDER_OPENAI: "OPENAI_API_KEY",
    }.get(provider)
    return os.environ.get(env_var) if env_var else None


def chat(provider, model_string, api_key, system, messages, max_tokens=DEFAULT_MAX_TOKENS) -> str:
    """Return the assistant's text reply.

    `messages` is a list of {"role": "user"|"assistant", "content": str}, starting
    with a user turn.
    """
    key = _resolve_key(provider, api_key)
    if not key:
        raise LLMError(
            f"No API key for provider '{provider}'. Add one in Settings → Models, "
            f"or set it in poc/.env."
        )
    if provider == config.PROVIDER_ANTHROPIC:
        return _anthropic_chat(model_string, key, system, messages, max_tokens)
    if provider == config.PROVIDER_OPENAI:
        return _openai_chat(model_string, key, system, messages, max_tokens)
    raise LLMError(f"Unknown provider: {provider!r}")


def chat_json(provider, model_string, api_key, system, messages, max_tokens=DEFAULT_MAX_TOKENS,
              schema: dict | None = None, name: str = "structured_output") -> dict:
    """Like chat(), but returns a parsed JSON object.

    When a schema is supplied, use provider-native structured output:
    Anthropic forced tool calls, OpenAI JSON schema response format.
    """
    if schema is not None:
        key = _resolve_key(provider, api_key)
        if not key:
            raise LLMError(
                f"No API key for provider '{provider}'. Add one in Settings → Models, "
                f"or set it in poc/.env."
            )
        if provider == config.PROVIDER_ANTHROPIC:
            return _anthropic_json_schema(model_string, key, system, messages, max_tokens, schema, name)
        if provider == config.PROVIDER_OPENAI:
            return _openai_json_schema(model_string, key, system, messages, max_tokens, schema, name)
        raise LLMError(f"Unknown provider: {provider!r}")

    raw = chat(provider, model_string, api_key, system, messages, max_tokens)
    return _parse_json(raw)


# --- providers ----------------------------------------------------------------
def _anthropic_chat(model_string, key, system, messages, max_tokens) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model=model_string,
            max_tokens=max_tokens,
            system=system or "",
            messages=messages,
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
    except anthropic.APIError as e:  # pragma: no cover - network dependent
        raise LLMError(f"Anthropic API error: {e}") from e
    return "".join(block.text for block in resp.content if block.type == "text").strip()


def _anthropic_json_schema(model_string, key, system, messages, max_tokens, schema, name) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    try:
        resp = client.messages.create(
            model=model_string,
            max_tokens=max_tokens,
            system=system or "",
            messages=messages,
            tools=[{
                "name": name,
                "description": "Emit the required structured decision object.",
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": name},
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
    except anthropic.APIError as e:  # pragma: no cover - network dependent
        raise LLMError(f"Anthropic API error: {e}") from e
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == name:
            data = getattr(block, "input", None)
            if isinstance(data, dict):
                return data
    raise LLMError(f"Anthropic model did not return required tool call: {name}")


def _openai_chat(model_string, key, system, messages, max_tokens) -> str:
    from openai import OpenAI, OpenAIError

    client = OpenAI(api_key=key, timeout=config.LLM_TIMEOUT_SECONDS)
    full = ([{"role": "system", "content": system}] if system else []) + list(messages)
    # Newer models require `max_completion_tokens` and reject `max_tokens`; older ones
    # are the reverse. Try the modern param first, fall back if the model complains.
    last_err = None
    for token_param in ("max_completion_tokens", "max_tokens"):
        try:
            resp = client.chat.completions.create(
                model=model_string, messages=full, **{token_param: max_tokens}
            )
            return (resp.choices[0].message.content or "").strip()
        except OpenAIError as e:  # pragma: no cover - network dependent
            last_err = e
            if "max_tokens" in str(e) or "max_completion_tokens" in str(e):
                continue  # token-param mismatch — try the other one
            break
    raise LLMError(f"OpenAI API error: {last_err}")


def _openai_json_schema(model_string, key, system, messages, max_tokens, schema, name) -> dict:
    from openai import OpenAI, OpenAIError

    client = OpenAI(api_key=key, timeout=config.LLM_TIMEOUT_SECONDS)
    full = ([{"role": "system", "content": system}] if system else []) + list(messages)
    last_err = None
    response_formats = (
        {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        },
        {"type": "json_object"},
    )
    for response_format in response_formats:
        for token_param in ("max_completion_tokens", "max_tokens"):
            try:
                resp = client.chat.completions.create(
                    model=model_string,
                    messages=full,
                    response_format=response_format,
                    **{token_param: max_tokens},
                )
                return _parse_json(resp.choices[0].message.content or "")
            except OpenAIError as e:  # pragma: no cover - network dependent
                last_err = e
                text = str(e)
                if "max_tokens" in text or "max_completion_tokens" in text:
                    continue
                if response_format.get("type") == "json_schema" and (
                    "response_format" in text or "json_schema" in text or "schema" in text
                ):
                    break
                raise LLMError(f"OpenAI API error: {e}") from e
    raise LLMError(f"OpenAI API error: {last_err}")


# --- JSON parsing -------------------------------------------------------------
def _parse_json(text: str) -> dict:
    """Lenient parse: try whole string, then the first {...} block, then fenced."""
    text = text.strip()
    # strip a ```json … ``` fence if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise LLMError(f"Model did not return valid JSON. Got: {text[:300]}")
