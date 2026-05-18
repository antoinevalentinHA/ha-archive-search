from jinja2 import Environment, FileSystemLoader

from ha_archive_search.webapp import (
    ParsedResults,
    VersionResult,
    FileResult,
    Hit,
    Summary,
)


env = Environment(
    loader=FileSystemLoader("src/ha_archive_search/templates"),
    autoescape=True,
)

template = env.get_template("index.html")


def render(parsed):
    return template.render(
        app_name="ha-archive-search",
        query="sensor.test",
        output="",
        error="",
        parsed=parsed,
        context=False,
        latest=False,
        all_versions=False,
        exclude_docs=False,
        docs_only=False,
    )


BASE_RESULTS = ParsedResults(
    versions=(
        VersionResult(
            version="2026-05-18_x",
            files=(
                FileResult(
                    path="config.yaml",
                    hits=(
                        Hit(line=42, content=" hello"),
                    ),
                ),
            ),
        ),
    ),
    summary=None,
)


def test_html_nominal_summary_badges():
    parsed = ParsedResults(
        versions=BASE_RESULTS.versions,
        summary=Summary(
            status="nominal",
            count=3,
            total=None,
            versions=2,
            duration="0.18",
            raw_footer=None,
        ),
    )

    html = render(parsed)

    assert '3 results' in html
    assert '2 versions' in html
    assert '0.18 s' in html

    assert 'class="badge badge-status-truncated"' not in html
    assert 'class="badge badge-status-timeout"' not in html


def test_html_truncated_badge():
    parsed = ParsedResults(
        versions=BASE_RESULTS.versions,
        summary=Summary(
            status="truncated",
            count=200,
            total=1247,
            versions=None,
            duration="0.32",
            raw_footer=None,
        ),
    )

    html = render(parsed)

    assert 'badge-status-truncated' in html
    assert '200 displayed' in html
    assert '1247' in html


def test_html_timeout_badge():
    parsed = ParsedResults(
        versions=BASE_RESULTS.versions,
        summary=Summary(
            status="timeout",
            count=50,
            total=None,
            versions=2,
            duration="30.00",
            raw_footer=None,
        ),
    )

    html = render(parsed)

    assert 'badge-status-timeout' in html
    assert '50 partial' in html
    assert '30.00 s' in html

