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
    _MAX_IMAGES_PER_DOC,
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


def test_parse_feed_no_media_leaves_image_urls_empty():
    docs = parse_feed(_SAMPLE_RSS, max_items=25)
    assert docs[0].image_urls == []


# ---------- feed image extraction (media:thumbnail / media:content / enclosure) ----------

_RSS_WITH_MEDIA_CONTENT = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
  <item>
    <title>Article With Media</title>
    <link>https://example.com/media-article</link>
    <description>&lt;p&gt;Summary text for the article with media content attached.&lt;/p&gt;</description>
    <media:content url="https://img.example.com/photo.jpg" type="image/jpeg" medium="image"/>
  </item>
</channel></rss>
"""

_RSS_WITH_THUMBNAIL_AND_CONTENT = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
  <item>
    <title>Article With Both</title>
    <link>https://example.com/both</link>
    <description>&lt;p&gt;Summary text for an article exposing both media tags.&lt;/p&gt;</description>
    <media:thumbnail url="https://img.example.com/thumb.jpg"/>
    <media:content url="https://img.example.com/photo.jpg" type="image/jpeg" medium="image"/>
  </item>
</channel></rss>
"""

_RSS_WITH_IMAGE_ENCLOSURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Article With Enclosure</title>
    <link>https://example.com/enclosure</link>
    <description>&lt;p&gt;Summary text for an article with an enclosure image.&lt;/p&gt;</description>
    <enclosure url="https://img.example.com/enclosure.jpg" type="image/jpeg" length="12345"/>
  </item>
</channel></rss>
"""

_RSS_WITH_MANY_IMAGES = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
  <item>
    <title>Article With Many Images</title>
    <link>https://example.com/many-images</link>
    <description>&lt;p&gt;Summary text for an article with many attached images.&lt;/p&gt;</description>
    <media:content url="https://img.example.com/1.jpg" type="image/jpeg" medium="image"/>
    <media:content url="https://img.example.com/2.jpg" type="image/jpeg" medium="image"/>
    <media:content url="https://img.example.com/3.jpg" type="image/jpeg" medium="image"/>
    <media:content url="https://img.example.com/4.jpg" type="image/jpeg" medium="image"/>
    <media:content url="https://img.example.com/5.jpg" type="image/jpeg" medium="image"/>
    <media:content url="https://img.example.com/6.jpg" type="image/jpeg" medium="image"/>
    <media:content url="https://img.example.com/7.jpg" type="image/jpeg" medium="image"/>
    <media:content url="https://img.example.com/8.jpg" type="image/jpeg" medium="image"/>
  </item>
</channel></rss>
"""


def test_parse_feed_reads_media_content_image():
    docs = parse_feed(_RSS_WITH_MEDIA_CONTENT, max_items=25)
    assert docs[0].image_urls == ["https://img.example.com/photo.jpg"]


def test_parse_feed_orders_thumbnail_before_media_content():
    # Both are collected now (not "first match wins") - thumbnail just
    # sorts first since it's the purpose-built lead-image signal.
    docs = parse_feed(_RSS_WITH_THUMBNAIL_AND_CONTENT, max_items=25)
    assert docs[0].image_urls == ["https://img.example.com/thumb.jpg", "https://img.example.com/photo.jpg"]


def test_parse_feed_reads_image_enclosure():
    docs = parse_feed(_RSS_WITH_IMAGE_ENCLOSURE, max_items=25)
    assert docs[0].image_urls == ["https://img.example.com/enclosure.jpg"]


def test_parse_feed_caps_images_at_max_per_doc():
    docs = parse_feed(_RSS_WITH_MANY_IMAGES, max_items=25)
    assert len(docs[0].image_urls) == _MAX_IMAGES_PER_DOC == 6
    assert docs[0].image_urls == [f"https://img.example.com/{i}.jpg" for i in range(1, 7)]


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


def test_extract_article_no_image_meta_leaves_image_urls_empty():
    doc = extract_article(_SAMPLE_ARTICLE_HTML, "https://example.com/audio-fix")
    assert doc.image_urls == []


_ARTICLE_HTML_WITH_OG_IMAGE = """
<html><head><title>How to Fix Audio Issues</title>
<meta property="og:image" content="https://img.example.com/og.jpg">
</head>
<body>
<article>
<h1>How to Fix Audio Issues in Microsoft Teams</h1>
<p>Check the physical mute switch on your headset first.</p>
<p>Then open Teams settings and select the correct audio device.</p>
</article>
</body></html>
"""

_ARTICLE_HTML_WITH_TWITTER_IMAGE_ONLY = """
<html><head><title>How to Fix Audio Issues</title>
<meta name="twitter:image" content="https://img.example.com/twitter.jpg">
</head>
<body>
<article>
<h1>How to Fix Audio Issues in Microsoft Teams</h1>
<p>Check the physical mute switch on your headset first.</p>
<p>Then open Teams settings and select the correct audio device.</p>
</article>
</body></html>
"""


def test_extract_article_reads_og_image():
    doc = extract_article(_ARTICLE_HTML_WITH_OG_IMAGE, "https://example.com/audio-fix")
    assert doc.image_urls == ["https://img.example.com/og.jpg"]


def test_extract_article_falls_back_to_twitter_image():
    doc = extract_article(_ARTICLE_HTML_WITH_TWITTER_IMAGE_ONLY, "https://example.com/audio-fix")
    assert doc.image_urls == ["https://img.example.com/twitter.jpg"]


# Realistic paragraph lengths matter here - trafilatura's content-vs-
# boilerplate classifier needs enough surrounding text per image to
# confidently keep it (verified live before writing this fixture; terser
# paragraphs cause it to drop the <graphic> elements entirely).
_ARTICLE_HTML_WITH_BODY_IMAGES = """
<html><head><title>How to Fix Audio Issues</title></head>
<body>
<nav><img src="https://img.example.com/nav-logo.png"></nav>
<article>
<h1>How to Fix Audio Issues in Microsoft Teams</h1>
<p>Check the physical mute switch on your headset first. This is a common cause of audio problems that many users overlook when troubleshooting their conferencing software.</p>
<img src="https://img.example.com/step1.jpg" alt="step 1">
<p>Then open Teams settings and select the correct audio device from the dropdown menu in the settings panel, which can be found under the general audio devices tab.</p>
<img src="https://img.example.com/step2.jpg" alt="step 2">
<p>Finally, restart the application and rejoin your meeting to confirm the audio issue has been resolved successfully.</p>
</article>
<footer><img src="https://img.example.com/ad-banner.png"></footer>
</body></html>
"""

_ARTICLE_HTML_WITH_OG_AND_BODY_IMAGE = """
<html><head><title>How to Fix Audio Issues</title>
<meta property="og:image" content="https://img.example.com/og.jpg">
</head>
<body>
<article>
<h1>How to Fix Audio Issues in Microsoft Teams</h1>
<p>Check the physical mute switch on your headset first. This is a common cause of audio problems that many users overlook when troubleshooting their conferencing software.</p>
<img src="https://img.example.com/step1.jpg" alt="step 1">
<p>Then open Teams settings and select the correct audio device from the dropdown menu in the settings panel, which can be found under the general audio devices tab.</p>
</article>
</body></html>
"""


def test_extract_article_reads_body_images_excluding_nav_and_footer():
    doc = extract_article(_ARTICLE_HTML_WITH_BODY_IMAGES, "https://example.com/audio-fix")
    assert doc.image_urls == ["https://img.example.com/step1.jpg", "https://img.example.com/step2.jpg"]


def test_extract_article_puts_og_image_first_then_body_images():
    doc = extract_article(_ARTICLE_HTML_WITH_OG_AND_BODY_IMAGE, "https://example.com/audio-fix")
    assert doc.image_urls == ["https://img.example.com/og.jpg", "https://img.example.com/step1.jpg"]


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


# ---------- show_images gating (feeds_only default / all / off) ----------

def _fake_get_for(content_type, body):
    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return _FakeResponse("", status_code=404)
        return _FakeResponse(body, content_type=content_type)
    return fake_get


@pytest.mark.parametrize("show_images,expected", [
    ("feeds_only", ["https://img.example.com/photo.jpg"]),  # default - feed images kept
    ("all", ["https://img.example.com/photo.jpg"]),
    ("off", []),
])
def test_fetch_source_gates_feed_image_by_show_images(show_images, expected):
    web = WebSourceConfig(tenant="t", site_url="https://x", source_list="News",
                          respect_robots=False, prefer_feeds=True, show_images=show_images)
    source = WebSourceRow(source_id="1", url="https://example.com/feed", enabled=True)

    docs = fetch_source(source, web, rate_limiter=_no_delay_limiter(),
                        http_get=_fake_get_for("application/rss+xml", _RSS_WITH_MEDIA_CONTENT))
    assert docs[0].image_urls == expected


@pytest.mark.parametrize("show_images,expected", [
    ("feeds_only", []),  # default - HTML-scraped images NOT shown
    ("all", ["https://img.example.com/og.jpg"]),
    ("off", []),
])
def test_fetch_source_gates_html_image_by_show_images(show_images, expected):
    web = WebSourceConfig(tenant="t", site_url="https://x", source_list="News",
                          respect_robots=False, prefer_feeds=True, show_images=show_images)
    source = WebSourceRow(source_id="1", url="https://example.com/audio-fix", enabled=True)

    docs = fetch_source(source, web, rate_limiter=_no_delay_limiter(),
                        http_get=_fake_get_for("text/html", _ARTICLE_HTML_WITH_OG_IMAGE))
    assert docs[0].image_urls == expected