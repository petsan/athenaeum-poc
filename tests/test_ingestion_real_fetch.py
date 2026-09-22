"""
Real network fetch (ingestion.py's fetch_url, added 2026-09-22) -- these
hit the actual internet from the real LXC 104 guest, no mocking for the
main path, same "verify empirically" convention as test_sandbox.py's real
kernel-feature tests. Deterministic edge cases (robots.txt unreachable,
DNS failure) use RFC-reserved/guaranteed-broken targets or narrow
monkeypatching specifically because a LIVE third-party site's exact
robots.txt content isn't something this suite should depend on staying
the same forever.
"""
import urllib.robotparser
import pytest
from athenaeum_body import ingestion
from athenaeum_body.ingestion import fetch_url, ingest, FetchError, IngestionRejected
from athenaeum_body.storage.content_addressed import ContentAddressedStore


def test_fetch_url_real_network_fetch_succeeds():
    source = fetch_url("http://info.cern.ch/hypertext/WWW/TheProject.html", license="public-domain")
    assert len(source.content) > 0
    assert source.license == "public-domain"
    assert source.robots_disallowed is False  # this page has no robots.txt at all -- fail-open


def test_fetch_url_result_flows_through_real_ingest_pipeline(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    source = fetch_url("http://info.cern.ch/hypertext/WWW/TheProject.html", license="public-domain")
    entry = ingest(source, cas)
    assert entry.metadata["license"] == "public-domain"
    assert entry.content_hash


def test_fetch_url_raises_fetch_error_on_unreachable_host():
    # .invalid is reserved by RFC 2606 to never resolve -- a real,
    # deterministic network failure, not a mock standing in for one.
    with pytest.raises(FetchError):
        fetch_url("http://this-host-does-not-exist.invalid/", license="public-domain")


def test_fetch_url_never_sends_credentials_or_api_key():
    """Section 6.6's hard floor: every fetch is a plain, unauthenticated
    GET. Checked structurally -- fetch_url's own source never references
    an Authorization header, API key, or token."""
    import inspect
    src = inspect.getsource(fetch_url)
    for forbidden in ("Authorization", "api_key", "apikey", "token="):
        assert forbidden not in src


def test_robots_allowed_fails_open_when_robots_txt_unreachable(monkeypatch):
    def broken_read(self):
        raise OSError("simulated: robots.txt unreachable")
    monkeypatch.setattr(urllib.robotparser.RobotFileParser, "read", broken_read)
    assert ingestion._robots_allowed("https://example.invalid/page", "TestBot") is True


def test_robots_disallowed_blocks_when_parser_says_so(monkeypatch):
    def fake_read(self):
        pass  # no-op -- can_fetch below is what we're controlling

    monkeypatch.setattr(urllib.robotparser.RobotFileParser, "read", fake_read)
    monkeypatch.setattr(urllib.robotparser.RobotFileParser, "can_fetch", lambda self, ua, url: False)
    assert ingestion._robots_allowed("https://example.invalid/blocked", "TestBot") is False
