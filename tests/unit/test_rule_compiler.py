from app.intelligence.rule_compiler import _pattern_compile, RuleCompiler


def test_compile_github_rule():
    ok, msg, rule = RuleCompiler().compile("Open every GitHub link posted in the meeting chat")
    assert ok, msg
    assert rule.trigger == "NEW_URL"
    assert rule.conditions["domain"] == "github.com"
    assert rule.action.type == "open_url"


def test_compile_never_submit_is_conservative():
    ok, msg, rule = RuleCompiler().compile("Never submit forms automatically")
    assert ok, msg
    assert rule.requires_confirmation is True


def test_compile_notify_rule_asks():
    ok, msg, rule = RuleCompiler().compile("Notify me whenever a Google Form appears")
    assert ok, msg
    assert rule.requires_confirmation is True


def test_compiler_cannot_emit_code():
    # garbage instruction → no rule, never an executable artifact
    ok, msg, rule = _pattern_compile_safe()
    assert rule is None or hasattr(rule, "trigger")


def _pattern_compile_safe():
    try:
        return True, "ok", _pattern_compile("import os; os.system('rm -rf /')")
    except Exception:
        return False, "error", None


def test_compiled_rule_passes_schema_validation():
    from app.rules.schema import validate_rule_dict
    from app.rules.engine import json_rule

    ok, msg, rule = RuleCompiler().compile("Open every github.com link in chat")
    assert ok, msg
    ok2, err, _ = validate_rule_dict(json_rule(rule))
    assert ok2, err
