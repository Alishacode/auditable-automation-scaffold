"""Deterministic scoring engine (slide 7 Scoring Builder: "Completely
deterministic."). Sums rule score deltas and maps the total onto a risk
level via the template version's ScoringConfig thresholds."""
from app.models.template import ScoringConfig


def compute_risk(rule_results: list[dict], scoring_config: ScoringConfig) -> tuple[int, str, list[str]]:
    """Returns (total_score, risk_level, reasons). `reasons` lists the
    human-readable explanation for every rule that fired — this is what
    powers the Reviewer's "Risk Reasons" list (slide 13)."""
    total = sum(r["score_delta_applied"] for r in rule_results)
    reasons = [r["reason"] for r in rule_results if r["passed"] and r["reason"]]

    if total <= scoring_config.low_max:
        level = "low"
    elif total <= scoring_config.medium_max:
        level = "medium"
    else:
        level = "high"

    return total, level, reasons
