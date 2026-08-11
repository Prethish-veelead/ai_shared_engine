"""Pure-logic unit tests for app/ingestion/web_fetcher.py and the
content_type=web schema. No live HTTP, no database - fetch_source's
network call is a plain injected function (not a mocking library, matching
this repo's existing test style), and the DB/reconcile/idempotent-resync/
bot-deletion acceptance criteria are verified live against the real
Postgres/Qdrant instance instead (see docs/WEB_SOURCE_BOT.md), same
pattern already used for app/db/list_tables.py this session.
"""
import pytest

from app.bots.schema import BotConfig, WebSourceConfig
from app.ingestion.web_fetcher import (
    ExtractedDoc,
    HostRateLimiter,
    SourceSkipped,
    WebSourceRow,
    _is_source_enabled,
    extract_article,
    fetch_source,
    is_allowed_by_robots,
    looks_like_feed,
    parse_feed,
)

# ---------- schema ----------

def _web_bot_kwargs(**overrides):
    base = dict(
        id="news", name="News Bot", route="/ask/news", content_type="web",
        web=WebSourceConfig(tenant="acme", site_url="https://acme.sharepoint.com/sites/News",
                            source_list="News Sources"),
        vectorstore={"collection": "news_col"},
        prompt={"system": "Answer only from the provided sources and cite them."},
    )
    base.update(overrides)
    return base


def test_web_bot_loads_with_web_block():
    bot = BotConfig(**_web_bot_kwargs())
    assert bot.content_type == "web"
    assert bot.sharepoint is None
    assert bot.web.source_list == "News Sources"


def test_web_bot_without_web_block_rejected():
    with pytest.raises(ValueError, match="no 'web' config"):
        BotConfig(**_web_bot_kwargs(web=None))


def test_web_bot_with_sharepoint_block_rejected():
    # A web bot must not ALSO set 'sharepoint' - the two are mutually
    # exclusive ways of describing a bot's content source.
    with pytest.raises(ValueError, match="not 'sharepoint'"):
        BotConfig(**_web_bot_kwargs(sharepoint={
            "tenant": "acme", "sites": [{"site_url": "https://x", "libraries": ["Docs"]}],
        }))


def test_library_bot_still_requires_sharepoint():
    with pytest.raises(ValueError, match="requires a 'sharepoint'"):
        BotConfig(
            id="hr", name="HR", route="/ask/hr", content_type="library",
            vectorstore={"collection": "hr_col"},
            prompt={"system": "Answer from HR docs."},
        )


# ---------- read_web_sources' enabled-column matching ----------

def test_is_source_enabled_matches_case_and_whitespace_insensitively():
    web = WebSourceConfig(tenant="t", site_url="https://x", source_list="News", enabled_value="yes")
    assert _is_source_enabled({"Enable": " Yes "}, web) is True
    assert _is_source_enabled({"Enable": "YES"}, web) is True
    assert _is_source_enabled({"Enable": "no"}, web) is False
    assert _is_source_enabled({}, web) is False  # missing column -> not enabled (opt-in, unlike the publish gates)


# ---------- robots.txt ----------

_ROBOTS_DISALLOW_ALL = "User-agent: *\nDisallow: /private/\n"


def test_robots_allows_when_no_robots_txt():
    assert is_allowed_by_robots(None, "VeeleadBot/1.0", "https://example.com/anything") is True


def test_robots_disallows_matching_path():
    assert is_allowed_by_robots(_ROBOTS_DISALLOW_ALL, "VeeleadBot/1.0",
                                "https://example.com/private/secret") is False


def test_robots_allows_non_matching_path():
    assert is_allowed_by_robots(_ROBOTS_DISALLOW_ALL, "VeeleadBot/1.0",
                                "https://example.com/public/page") is True


# ---------- feed detection + parsing ----------

_SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Example Feed</title>
  <item>
    <title>First Article</title>
    <link>https://example.com/first</link>
    <description>&lt;p&gt;This is the first article's summary text.&lt;/p&gt;</description>
    <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Second Article</title>
    <link>https://example.com/second</link>
    <description>&lt;p&gt;This is the second article's summary text.&lt;/p&gt;</description>
    <pubDate>Tue, 02 Jan 2026 00:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


def test_looks_like_feed_by_content_type():
    assert looks_like_feed("application/rss+xml; charset=utf-8", "") is True


def test_looks_like_feed_by_body_sniff_when_mislabeled():
    assert looks_like_feed("text/html", _SAMPLE_RSS) is True


def test_looks_like_feed_false_for_plain_html():
    assert looks_like_feed("text/html", "<html><body>Hello</body></html>") is False


def test_parse_feed_expands_entries():
    docs = parse_feed(_SAMPLE_RSS, max_items=25)
    assert len(docs) == 2
    assert docs[0].title == "First Article"
    assert docs[0].url == "https://example.com/first"
    assert "first article" in docs[0].text.lower()
    assert docs[1].title == "Second Article"


def test_parse_feed_caps_at_max_items():
    docs = parse_feed(_SAMPLE_RSS, max_items=1)
    assert len(docs) == 1


# ---------- article extraction ----------

_SAMPLE_ARTICLE_HTML = """
<html><head><title>How to Fix Audio Issues</title></head>
<body>
<nav>Home | About | Contact</nav>
<header><div class="ad">Advertisement banner here</div></header>
<article>
<h1>How to Fix Audio Issues in Microsoft Teams</h1>
<p>Check the physical mute switch on your headset first.</p>
<p>Then open Teams settings and select the correct audio device.</p>
</article>
<footer>Copyright 2026. All rights reserved. Privacy Policy | Terms</footer>
</body></html>
"""


def test_extract_article_gets_main_text():
    doc = extract_article(_SAMPLE_ARTICLE_HTML, "https://example.com/audio-fix")
    assert doc is not None
    assert "physical mute switch" in doc.text
    assert "correct audio device" in doc.text
    assert doc.url == "https://example.com/audio-fix"


def test_extract_article_returns_none_for_empty_page():
    doc = extract_article("<html><body></body></html>", "https://example.com/empty")
    assert doc is None


# ---------- rate limiter ----------

def test_rate_limiter_waits_between_same_host_requests():
    clock = {"t": 0.0}
    waited = []
    limiter = HostRateLimiter(2.0, now=lambda: clock["t"], sleep=lambda s: waited.append(s))

    limiter.wait_for("https://example.com/a")
    assert waited == []  # first request to this host - no prior request to wait on

    clock["t"] = 0.5  # only 0.5s elapsed, delay is 2.0s
    limiter.wait_for("https://example.com/b")
    assert waited == [1.5]


def test_rate_limiter_does_not_wait_for_different_hosts():
    clock = {"t": 0.0}
    waited = []
    limiter = HostRateLimiter(2.0, now=lambda: clock["t"], sleep=lambda s: waited.append(s))

    limiter.wait_for("https://example.com/a")
    limiter.wait_for("https://other.com/b")
    assert waited == []


# ---------- fetch_source orchestration (injected http_get - no real network) ----------

class _FakeResponse:
    def __init__(self, text, content_type="text/html", status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _no_delay_limiter():
    return HostRateLimiter(0.0)


def test_fetch_source_skips_when_robots_disallowed_and_never_fetches_the_page():
    web = WebSourceConfig(tenant="t", site_url="https://x", source_list="News",
                          respect_robots=True, user_agent="TestBot/1.0")
    source = WebSourceRow(source_id="1", url="https://example.com/private/page", enabled=True)

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return _FakeResponse(_ROBOTS_DISALLOW_ALL, content_type="text/plain")
        raise AssertionError("Should never fetch the disallowed page itself")

    with pytest.raises(SourceSkipped, match="robots"):
        fetch_source(source, web, rate_limiter=_no_delay_limiter(), http_get=fake_get)
    assert calls == ["https://example.com/robots.txt"]  # only robots.txt was ever requested


def test_fetch_source_extracts_article_when_allowed():
    web = WebSourceConfig(tenant="t", site_url="https://x", source_list="News",
                          respect_robots=True, prefer_feeds=True, user_agent="TestBot/1.0")
    source = WebSourceRow(source_id="1", url="https://example.com/audio-fix", enabled=True)

    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return _FakeResponse("", status_code=404)
        return _FakeResponse(_SAMPLE_ARTICLE_HTML, content_type="text/html")

    docs = fetch_source(source, web, rate_limiter=_no_delay_limiter(), http_get=fake_get)
    assert len(docs) == 1
    assert "physical mute switch" in docs[0].text


def test_fetch_source_expands_feed_when_prefer_feeds():
    web = WebSourceConfig(tenant="t", site_url="https://x", source_list="News",
                          respect_robots=False, prefer_feeds=True, max_items_per_source=25)
    source = WebSourceRow(source_id="1", url="https://example.com/feed", enabled=True)

    def fake_get(url, **kwargs):
        return _FakeResponse(_SAMPLE_RSS, content_type="application/rss+xml")

    docs = fetch_source(source, web, rate_limiter=_no_delay_limiter(), http_get=fake_get)
    assert len(docs) == 2


def test_fetch_source_raises_source_skipped_on_dead_url():
    # SourceSkipped, not a bare empty list - see its docstring for why a
    # fetch failure must stay distinguishable from "fetched fine, found
    # nothing" (run_web_sync wipes previous content in the latter case,
    # never the former).
    web = WebSourceConfig(tenant="t", site_url="https://x", source_list="News", respect_robots=False)
    source = WebSourceRow(source_id="1", url="https://example.com/dead", enabled=True)

    def fake_get(url, **kwargs):
        raise ConnectionError("simulated dead host")

    with pytest.raises(SourceSkipped, match="fetch failed"):
        fetch_source(source, web, rate_limiter=_no_delay_limiter(), http_get=fake_get)