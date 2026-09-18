from app.speech.commands import parse_command


def test_stop():
    assert parse_command("stop").name == "emergency_stop"


def test_pause_resume():
    assert parse_command("pause").name == "pause"
    assert parse_command("resume").name == "resume"


def test_take_over():
    assert parse_command("take over").name == "take_over"


def test_manual_mode():
    assert parse_command("manual mode").name == "manual_mode"


def test_queries():
    assert parse_command("What did you detect?").name == "what_detected"
    assert parse_command("What did you do?").name == "what_did"


def test_rules_commands():
    assert parse_command("show active rules").name == "show_rules"
    cmd = parse_command("disable rule open_github_links")
    assert cmd.name == "disable_rule" and cmd.argument == "open_github_links"


def test_mode_switch():
    cmd = parse_command("switch to assist")
    assert cmd.name == "mode" and cmd.argument == "assist"


def test_unknown():
    assert parse_command("hello there") is None
