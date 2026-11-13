import sys
from types import SimpleNamespace

from pipeline.extract import ExtractionService
from pipeline.extract import _salary_fixed
from pipeline.text import html_to_text


def test_missing_key_uses_local_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = ExtractionService(prompt_for_key=False)
    assert service.provider == "heuristic"
    assert "No OpenAI API key" in service.warning


def test_invalid_key_uses_local_fallback(monkeypatch):
    class InvalidClient:
        def __init__(self, **_kwargs):
            self.models = self

        def list(self):
            raise RuntimeError("invalid key")

    monkeypatch.setenv("OPENAI_API_KEY", "invalid-test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=InvalidClient))
    service = ExtractionService(prompt_for_key=False)
    assert service.provider == "heuristic"
    assert "missing or invalid" in service.warning


def test_escaped_html_and_pay_range_are_decoded_correctly():
    assert html_to_text("&lt;div&gt;Local Pay Range&lt;/div&gt;") == "Local Pay Range"
    low, high, currency, _ = _salary_fixed("Local Pay Range $182,400\u2014$247,000 USD")
    assert (low, high, currency) == (182400.0, 247000.0, "USD")


def test_internal_boilerplate_is_not_an_internship():
    from pipeline.extract import _heuristic
    from pipeline.models import RawPosting

    record = _heuristic(RawPosting(
        source="greenhouse", source_id="1", source_url="https://example.test/1",
        company="Acme", title="Data Engineer", location_text="Austin, US",
        description_text="Work with internal platform teams and production systems.",
    ))
    assert record.employment_type is None
