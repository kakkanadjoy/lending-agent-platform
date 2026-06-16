"""Guardrails around the one generative step.

Five deterministic guards wrap the draft node — two protect the LLM's input,
three validate its output. Every guard is rule-based, not generative: a
regulator can read each as a plain rule, and none of them adds a second
hallucination surface. The LLM is the only non-deterministic thing in the
building; these guards box it in on both sides.

INBOUND  (before text reaches the LLM)
  1. redact_pii        — strip PII from untrusted borrower text (Presidio)
  2. screen_injection  — flag prompt-injection attempts

OUTBOUND (after the LLM drafts, before a human sees it)
  3. check_numbers     — every number in the draft must match a verified fact
  4. check_citations   — every cited section must exist in the corpus
  5. check_scope       — the draft must not introduce out-of-scope claims

The outbound three are the heart of the facts-only contract: the LLM drafts,
deterministic code checks its work. A fabricated number or invented citation
is caught here, before it can reach a human — so the model can corrupt a
draft, never a decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── result type ──────────────────────────────────────────────────────────

@dataclass
class GuardResult:
    ok: bool
    findings: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> "GuardResult":
        return GuardResult(False, self.findings + [msg])


# ── 1. PII redaction (inbound) ────────────────────────────────────────────
# Presidio is the implementation; redact_pii is the seam. Imported lazily so
# the spaCy model only loads when borrower text actually needs scrubbing.

_PII_ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN",
                 "US_BANK_NUMBER", "CREDIT_CARD", "US_DRIVER_LICENSE",
                 "LOCATION", "IP_ADDRESS"]


def redact_pii(text: str) -> str:
    """Replace detected PII with typed placeholders, e.g. <PERSON>. Borrower
    text is untrusted and may carry PII that must not reach the LLM or a log."""
    if not text:
        return text
    analyzer, anonymizer = _presidio()
    results = analyzer.analyze(text=text, entities=_PII_ENTITIES, language="en")
    return anonymizer.anonymize(text=text, analyzer_results=results).text


def _presidio():
    """Build the Presidio analyzer/anonymizer once, configured to use the
    small spaCy model (en_core_web_sm, ~12MB) — plenty for spotting PII
    entities, and far lighter than the large default."""
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _build():
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        })
        analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
        return analyzer, AnonymizerEngine()

    return _build()


# ── 2. prompt-injection screen (inbound) ──────────────────────────────────
# Deterministic patterns for the realistic threat: borrower text trying to
# hijack the model's instructions. Not an LLM judge — plain rules.

_INJECTION_PATTERNS = [
    r"ignore (all |the |your )?(previous|prior|above)",
    r"disregard (the |your |all )?(above|previous|instructions|policy)",
    r"forget (your |the |all )?(instructions|rules|policy)",
    r"you are now",
    r"new instructions?:",
    r"system prompt",
    r"act as (if|though|an?)",
    r"recommend (approval|that we approve)",
    r"override",
    r"admin mode",
]


def screen_injection(text: str) -> GuardResult:
    """Flag borrower text that looks like a prompt-injection attempt."""
    result = GuardResult(True)
    low = (text or "").lower()
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, low):
            result = result.fail(f"possible injection: matched /{pat}/")
    return result


# ── 3. numeric fidelity (outbound) — the star ─────────────────────────────

_NUM = re.compile(r"-?\d+\.?\d*")
# Loan IDs and similar identifiers: a letter-run, a hyphen, then alnum chunks
# (e.g. LN-DEMO-CLEAN, LN-2026-02002, LN-1). Their digits are not financial
# claims, so we remove them before the numeric scan.
_IDENTIFIER = re.compile(r"\b[A-Za-z]{2,}-[A-Za-z0-9-]+")


def _verified_numbers(state: dict) -> set[str]:
    """Every number the draft is allowed to state, drawn from the verified
    facts on the state: the loan financials, the EWS score, and the observed/
    threshold values from each fired exception. We also include common ROUNDED
    forms (2dp, 1dp, integer) of each value, because a draft legitimately
    rounds for readability (an EWS of 0.002 shown as 0.00 is not a fabrication)."""
    raw_values: set[float] = set()
    loan = state.get("loan", {})
    for key in ("dscr", "dscr_prior", "leverage", "utilization", "commitment"):
        v = loan.get(key)
        if v is not None:
            raw_values.add(float(v))
    if "ews_score" in state:
        raw_values.add(float(state["ews_score"]))
    for exc in state.get("exceptions", []):
        for key in ("observed", "threshold"):
            if exc.get(key) is not None:
                raw_values.add(float(exc[key]))

    out: set[str] = set()
    for v in raw_values:
        # exact (trimmed) plus rounded representations the draft might use
        for s in (f"{v:.4f}", f"{v:.3f}", f"{v:.2f}", f"{v:.1f}", f"{v:.0f}", str(v)):
            out.add(s)
            if "." in s:
                out.add(s.rstrip("0").rstrip("."))
    return out


def check_numbers(review_text: str, state: dict) -> GuardResult:
    result = GuardResult(True)
    allowed = _verified_numbers(state)
    text = _SECTION.sub(" ", review_text or "")
    text = _IDENTIFIER.sub(" ", text)
    text = re.sub(r'\$[\d,]+', lambda m: m.group().replace(',', '').replace('$', ''), text)  # normalize $250,000 → 250000
    text = re.sub(r'\d+\.?\d*x?\s+to\s+\d+\.?\d*x?', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'(above|below|over|under|exceeds?|minimum|maximum)\s+\d+\.?\d*x?', ' ', text, flags=re.IGNORECASE)
    for raw in _NUM.findall(text):
        norm = raw.rstrip("0").rstrip(".") if "." in raw else raw
        if raw in allowed or norm in allowed:
            continue
        try:
            fv = round(float(raw), 4)
            if f"{fv:.4f}".rstrip("0").rstrip(".") in allowed or str(fv) in allowed:
                continue
        except ValueError:
            pass
        result = result.fail(f"unverified number in draft: {raw}")
    return result


# ── 4. citation validity (outbound) ───────────────────────────────────────

_SECTION = re.compile(r"section\s+(\d+(?:\.\d+)*)", re.IGNORECASE)


def check_citations(review_text: str, valid_sections: set[str]) -> GuardResult:
    """Every section the draft cites must exist in the corpus."""
    result = GuardResult(True)
    for sec in _SECTION.findall(review_text or ""):
        if sec not in valid_sections:
            result = result.fail(f"citation to non-existent section: {sec}")
    return result


# ── 5. scope grounding (outbound, light) ──────────────────────────────────

_OUT_OF_SCOPE = [
    r"\b\d+[- ]year relationship\b",
    r"\bpersonal(ly)? (know|acquainted|friend)\b",
    r"\bguarantee[ds]? (approval|renewal)\b",
    r"\bno risk\b",
]


def check_scope(review_text: str) -> GuardResult:
    """Catch a few classes of invented narrative the draft must not introduce
    (claims not traceable to the gathered data). A light check — full semantic
    grounding is a production refinement."""
    result = GuardResult(True)
    low = (review_text or "").lower()
    for pat in _OUT_OF_SCOPE:
        if re.search(pat, low):
            result = result.fail(f"out-of-scope claim: matched /{pat}/")
    return result


# ── compose the outbound band ─────────────────────────────────────────────

def validate_draft(review_text: str, state: dict,
                   valid_sections: set[str] | None = None) -> GuardResult:
    """Run all outbound checks. The draft passes only if every guard passes."""
    sections = valid_sections or {
        c.get("section") for c in state.get("citations", []) if c.get("section")
    }
    findings: list[str] = []
    for res in (check_numbers(review_text, state),
                check_citations(review_text, sections),
                check_scope(review_text)):
        if not res.ok:
            findings.extend(res.findings)
    return GuardResult(not findings, findings)
