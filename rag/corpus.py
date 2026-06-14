"""Build the policy corpus from the same policy.yaml the engine evaluates.

This is the single-source-of-truth payoff: the text a verdict cites comes
from the exact rule that fired, so a citation can never describe a policy
different from the one enforced. One chunk per policy section keeps citations
exact — we cite section 4.3.1 because the chunk *is* section 4.3.1.

The corpus is just a list of chunks here; ingest.py embeds and stores them.
"""
from __future__ import annotations

import pathlib

import yaml

POLICY_FILE = pathlib.Path(__file__).parents[1] / "rules" / "policy.yaml"


def build_corpus() -> list[dict]:
    """One chunk per rule: the policy text plus the metadata needed to cite it."""
    policy = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    chunks = []
    for rule in policy["rules"]:
        # The retrievable text leads with the human title and section so both
        # lexical and semantic search have something natural to match on,
        # followed by the actual policy language.
        text = f"Section {rule['section']} — {rule['title']}.\n{rule['policy_text'].strip()}"
        chunks.append({
            "chunk_id": f"policy-{rule['code']}",
            "code": rule["code"],
            "section": rule["section"],
            "title": rule["title"],
            "text": text,
        })
    return chunks


if __name__ == "__main__":
    corpus = build_corpus()
    print(f"Built {len(corpus)} policy chunks:")
    for c in corpus:
        print(f"  {c['section']:8} {c['code']:18} {c['title']}")
