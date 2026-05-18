from ha_archive_search.webapp import (
    Summary,
    render_markdown_summary,
)


def test_render_markdown_summary_nominal():
    md = render_markdown_summary(
        Summary(
            status="nominal",
            count=3,
            total=None,
            versions=2,
            duration="0.18",
            raw_footer=None,
        )
    )

    assert "## Summary" in md
    assert "- Results: `3`" in md
    assert "- Versions: `2`" in md
    assert "- Duration: `0.18 s`" in md

    assert "Status:" not in md
    assert "failed" not in md


def test_render_markdown_summary_truncated():
    md = render_markdown_summary(
        Summary(
            status="truncated",
            count=200,
            total=1247,
            versions=None,
            duration="0.32",
            raw_footer=None,
        )
    )

    assert "## Summary" in md
    assert "- Status: `truncated`" in md
    assert "200 displayed" in md
    assert "1247" in md
    assert "- Duration: `0.32 s`" in md


def test_render_markdown_summary_timeout():
    md = render_markdown_summary(
        Summary(
            status="timeout",
            count=50,
            total=None,
            versions=2,
            duration="30.00",
            raw_footer=None,
        )
    )

    assert "## Summary" in md
    assert "- Status: `timeout`" in md
    assert "50 partial" in md
    assert "- Versions: `2`" in md
    assert "- Duration: `30.00 s`" in md


def test_render_markdown_summary_failed():
    md = render_markdown_summary(None)

    assert "## Summary" in md
    assert "- Summary parsing: `failed`" in md

