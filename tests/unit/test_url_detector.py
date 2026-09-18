from app.perception.url_detector import URLDetector


def test_extracts_plain_url():
    urls = URLDetector().extract("Assignment repository: https://github.com/example/repository")
    assert urls == ["https://github.com/example/repository"]


def test_extracts_schemeless_and_www():
    d = URLDetector()
    assert d.extract("see github.com/example/repo")[0] == "https://github.com/example/repo"
    assert d.extract("go to www.github.com/x")[0] == "https://github.com/x"


def test_strips_trailing_punctuation():
    urls = URLDetector().extract("it's at https://github.com/a/b.")
    assert urls == ["https://github.com/a/b"]


def test_normalizes_host_and_www():
    d = URLDetector()
    assert d.normalize("HTTPS://WWW.GitHub.com/a/") == "https://github.com/a"


def test_shortener_detection():
    d = URLDetector(shorteners=["bit.ly"])
    assert d.is_shortener("https://bit.ly/3xY")
    assert not d.is_shortener("https://github.com/x")
