"""Build the prompt for the renewal-review draft.

The prompt hands the model ONLY the verified facts already on the state — the
loan financials, the rules verdict, the EWS score, the retrieved policy
sections — and instructs it to write the review using only those facts. This
is where "facts-only" is REQUESTED; the outbound guardrails are where it's
ENFORCED. Belt and suspenders: ask the model to behave, then verify it did.

Note what the prompt forbids: inventing numbers, citing sections not provided,
and making a recommendation (the human decides — the bright line). The model
assembles; it does not decide.
"""
from __future__ import annotations

SYSTEM = (
    "You are a credit analyst assistant drafting an annual loan renewal review "
    "for a portfolio manager to read and verify. Write only from the facts "
    "provided. Rules you must follow:\n"
    "- Use only the numbers given. Never invent or estimate a figure.\n"
    "- Cite only the policy sections provided, by their exact section number.\n"
    "- Do not make an approval or decline recommendation; that is the "
    "underwriter's decision. End with a neutral note that the underwriter will "
    "complete the recommendation.\n"
    "- Be concise and factual. No relationship history, no speculation, no "
    "claims that are not in the facts below."
)


def build_user_prompt(state: dict) -> str:
    loan = state.get("loan", {})
    lines = [
        f"Loan: {loan.get('loan_id')}",
        f"Facility type: {loan.get('facility_type')}",
        f"Commitment: {loan.get('commitment')}",
        f"DSCR: {loan.get('dscr')} (prior year: {loan.get('dscr_prior')})",
        f"Leverage: {loan.get('leverage')}",
        f"Utilization: {loan.get('utilization')}",
        f"Early-warning deterioration score: {state.get('ews_score')}",
        "",
    ]

    exceptions = state.get("exceptions", [])
    if exceptions:
        lines.append("Policy exceptions found by the rules engine:")
        for exc in exceptions:
            lines.append(
                f"- {exc['code']} ({exc['severity']}): observed "
                f"{exc['observed']} vs threshold {exc['threshold']}, "
                f"governed by section {exc['section']}."
            )
    else:
        lines.append("No policy exceptions were found.")
    lines.append("")

    citations = state.get("citations", [])
    if citations:
        lines.append("Relevant policy text (cite these section numbers only):")
        for c in citations:
            lines.append(f"- Section {c['section']}: {c['body']}")
    lines.append("")
    lines.append("Write the renewal review now, following all the rules.")
    return "\n".join(lines)
