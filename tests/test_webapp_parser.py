from ha_archive_search.webapp import parse_compact_output


BULLET = "\u2022"


def test_parse_compact_nominal_footer():
    output = (
        "[2026-05-18_x] config.yaml:12: hello\n"
        f"3 results across 2 versions  {BULLET}  duration 0.18 s"
    )

    parsed = parse_compact_output(output)

    assert parsed.summary is not None
    assert parsed.summary.status == "nominal"
    assert parsed.summary.count == 3
    assert parsed.summary.versions == 2
    assert parsed.summary.total is None
    assert parsed.summary.duration == "0.18"


def test_parse_compact_truncated_footer():
    output = f"results truncated: 200 displayed out of at least 1247  {BULLET}  duration 0.32 s"

    parsed = parse_compact_output(output)

    assert parsed.summary is not None
    assert parsed.summary.status == "truncated"
    assert parsed.summary.count == 200
    assert parsed.summary.total == 1247
    assert parsed.summary.versions is None
    assert parsed.summary.duration == "0.32"


def test_parse_compact_timeout_footer():
    output = f"query timeout: 50 partial results (not guaranteed) across 2 versions  {BULLET}  duration 30.00 s"

    parsed = parse_compact_output(output)

    assert parsed.summary is not None
    assert parsed.summary.status == "timeout"
    assert parsed.summary.count == 50
    assert parsed.summary.versions == 2
    assert parsed.summary.total is None
    assert parsed.summary.duration == "30.00"


def test_parse_compact_unknown_footer_is_not_summary():
    parsed = parse_compact_output("something unrecognized")

    assert parsed.summary is None


def test_parse_compact_preserves_trailing_spaces_in_hit_content():
    output = "[2026-05-18_x] file.yaml:42: content with trailing   "

    parsed = parse_compact_output(output)
    hit = parsed.versions[0].files[0].hits[0]

    assert hit.content == " content with trailing   "
