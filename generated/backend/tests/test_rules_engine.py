"""Deterministic rule-engine tests, generated from the template spec.
Every rule gets a happy-path (condition met) and an edge-case (field
missing) test — see slide 12 "Working Rhythm" and slide 14 "Rule
Correctness"."""
from uuid import uuid4

from app.models.template import Rule, RuleCategory, RuleCondition
from app.services.rules_engine import evaluate_rule


def test_rule_completeness_id_fires_when_condition_met():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="RULE_COMPLETENESS_ID",
                category=RuleCategory.COMPLETENESS, field_path="documents.id_proof",
                condition=RuleCondition.EQUALS,
                comparison_value={"value": 'missing'}, score_delta=-15,
                reason="Missing mandatory ID")
    doc = {}
    for part in reversed("documents.id_proof".split(".")):
        doc = {part: 'missing'} if part == "documents.id_proof".split(".")[-1] else {part: doc}
    fired, delta = evaluate_rule(rule, doc)
    assert fired is True
    assert delta == -15


def test_rule_completeness_id_does_not_fire_on_missing_field():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="RULE_COMPLETENESS_ID",
                category=RuleCategory.COMPLETENESS, field_path="documents.id_proof",
                condition=RuleCondition.EQUALS,
                comparison_value={"value": 'missing'}, score_delta=-15,
                reason="Missing mandatory ID")
    fired, delta = evaluate_rule(rule, {})  # edge case: field entirely absent
    if RuleCondition.EQUALS == RuleCondition.MISSING:
        assert fired is True
    else:
        assert fired is False
        assert delta == 0


def test_rule_id_412_fires_when_condition_met():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="RULE_ID_412",
                category=RuleCategory.VALIDATION, field_path="documents.id_proof",
                condition=RuleCondition.EQUALS,
                comparison_value={"value": 'missing'}, score_delta=50,
                reason="Missing Government ID details in JSON")
    doc = {}
    for part in reversed("documents.id_proof".split(".")):
        doc = {part: 'missing'} if part == "documents.id_proof".split(".")[-1] else {part: doc}
    fired, delta = evaluate_rule(rule, doc)
    assert fired is True
    assert delta == 50


def test_rule_id_412_does_not_fire_on_missing_field():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="RULE_ID_412",
                category=RuleCategory.VALIDATION, field_path="documents.id_proof",
                condition=RuleCondition.EQUALS,
                comparison_value={"value": 'missing'}, score_delta=50,
                reason="Missing Government ID details in JSON")
    fired, delta = evaluate_rule(rule, {})  # edge case: field entirely absent
    if RuleCondition.EQUALS == RuleCondition.MISSING:
        assert fired is True
    else:
        assert fired is False
        assert delta == 0


def test_rule_eligibility_salary_fires_when_condition_met():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="RULE_ELIGIBILITY_SALARY",
                category=RuleCategory.ELIGIBILITY, field_path="salary_amount",
                condition=RuleCondition.GREATER_THAN,
                comparison_value={"value": 0}, score_delta=5,
                reason="Salary present and eligible for payroll run")
    doc = {}
    for part in reversed("salary_amount".split(".")):
        doc = {part: 1} if part == "salary_amount".split(".")[-1] else {part: doc}
    fired, delta = evaluate_rule(rule, doc)
    assert fired is True
    assert delta == 5


def test_rule_eligibility_salary_does_not_fire_on_missing_field():
    rule = Rule(id=uuid4(), template_version_id=uuid4(), rule_key="RULE_ELIGIBILITY_SALARY",
                category=RuleCategory.ELIGIBILITY, field_path="salary_amount",
                condition=RuleCondition.GREATER_THAN,
                comparison_value={"value": 0}, score_delta=5,
                reason="Salary present and eligible for payroll run")
    fired, delta = evaluate_rule(rule, {})  # edge case: field entirely absent
    if RuleCondition.GREATER_THAN == RuleCondition.MISSING:
        assert fired is True
    else:
        assert fired is False
        assert delta == 0
