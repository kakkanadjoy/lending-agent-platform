"""The generation seam — one function the draft node calls to get text.

`generate(prompt)` returns model text. Behind it sits Azure Foundry's
gpt-4.1-mini, but the node doesn't know or care which model answers — same
seam idea as the repository (database) and the rules engine.

If no Azure credentials are configured, `generate` returns None and the draft
node falls back to its templated stub. So the whole platform runs offline for
development and tests; real generation switches on the moment a .env is filled
in — no code change. The LLM is an enhancement, not a hard dependency.

Expected environment (a .env at the project root, loaded by the caller):
    AZURE_OPENAI_ENDPOINT      https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_KEY       <key>
    AZURE_OPENAI_DEPLOYMENT    gpt-4.1-mini
    AZURE_OPENAI_API_VERSION   2024-12-01-preview
"""
from __future__ import annotations

import functools
import os
from typing import Optional


def is_configured() -> bool:
    return bool(os.environ.get("AZURE_OPENAI_ENDPOINT")
                and os.environ.get("AZURE_OPENAI_API_KEY")
                and os.environ.get("AZURE_OPENAI_DEPLOYMENT"))


@functools.lru_cache(maxsize=1)
def _client():
    """Build the Azure OpenAI client once. Imported lazily so the package is
    only needed when real generation is actually used."""
    from openai import AzureOpenAI
    return AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    )


def generate(system: str, user: str, temperature: float = 0.2) -> Optional[str]:
    """Return generated text, or None if no model is configured (so the caller
    falls back to the stub). Low temperature: this is a factual credit memo,
    not creative writing — we want consistent, grounded output."""
    if not is_configured():
        return None
    client = _client()
    resp = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=600,
    )
    return resp.choices[0].message.content
