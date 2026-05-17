# Changelog

All notable changes to this project will be documented in this file.

---

## [0.2.1] — 2026-05-17

### Added

#### Docker / Deployment

- `docker/docker-compose.synology.yml`
  - Dedicated Synology DSM deployment example.
  - Documents DSM ACL traversal limitations on mounted shared folders.
  - Explicit `user: "0:0"` compatibility override for restrictive DSM ACL environments.

### Changed

#### Documentation

- `README.md`
  - Added Synology DSM deployment section.
  - Documented typical `/versions` permission failure on DSM systems.
  - Clarified rationale for root container execution on DSM deployments.

---

## [0.2.0] — 2026-05-17

### Added

#### Webapp

- `webapp.py`: `parse_compact_output()` — structured parser for compact engine stdout.
  - Parses each match line via `COMPACT_LINE_RE` into a `{version → {path → [hits]}}` hierarchy.
  - Parses footer line via `SUMMARY_RE` into `{count, versions, duration}` summary dict.
  - Returns `(None, summary)` on empty result set; webapp falls back to raw `&lt;pre&gt;` block.
  - Context mode (`--mode context`) bypasses parser; raw fallback applies.
- `webapp.py`: `COMPACT_LINE_RE`, `SUMMARY_RE` — compiled regex constants for stdout parsing.
- `webapp.py`: `parsed` and `summary` passed to template on every search response.
- `templates/index.html`: structured result renderer.
  - KPI badge row: result count, version count, duration.
  - Per-version block with monospace header.
  - Per-file collapsible `&lt;details&gt;` block with occurrence count.
  - Per-match hit row: line number + content, no horizontal scroll.
  - Mobile-first layout: adaptive grid, block summary on narrow viewport.
  - Raw `&lt;pre&gt;` fallback preserved for context mode and unparsable output.

### Changed

- Result rendering: compact mode now produces structured HTML instead of raw stdout dump.
- No engine changes. No new dependencies.

---

## [0.1.0] — 2026-05-16

Initial release.

### Added

#### Engine

- `src/ha_archive_search/engine.py`: bounded CLI search engine for archived Home Assistant versions.
  - Nominal backend: ripgrep (`rg`), automatic fallback to GNU grep with explicit warning.
  - Version resolution: `--latest` (default), `--version <prefix>`, `--all-versions`.
  - Documentation scope control: `--exclude-docs`, `--docs-only`.
  - Output modes: `compact` (default), `context`.
  - Perimeter guard: all paths verified against `VERSIONS_ROOT` via `os.path.realpath()` before any read.
  - Result bounds: configurable with server-enforced hard ceilings (results: 2000, context: 50 lines, timeout: 30 s).
  - Color output: automatic TTY detection via `sys.stdout.isatty()`. No user flag.
  - Exit codes: `0` (ok), `1` (usage error), `2` (environment error), `3` (timeout).
  - stdlib only. No third-party dependency.

#### Webapp

- `src/ha_archive_search/webapp.py`: Flask presentation layer consuming the CLI engine via `subprocess`.
  - Routes: `GET /` (form), `POST /search` (search), `POST /export` (Markdown download), `GET /health` (status JSON).
  - Server-side validation: query length, mutual exclusion of `--exclude-docs` / `--docs-only`, mutual exclusion of `--latest` / `--all-versions`.
  - Markdown export: minimal envelope around exact engine stdout. No parsing, no reformatting.
  - Mono-process threading lock with explicit multi-worker warning.
  - No client-side JavaScript. No application authentication. HTTP only (LAN/VPN perimeter).
- `src/ha_archive_search/templates/index.html`: server-rendered search form.
  - Fields: query, context mode, latest only, all versions, exclude documentation, documentation only.
  - Results rendered as raw `<pre>` block — engine stdout displayed as-is, no parsing.
  - Error block for validation and engine errors.
  - Responsive layout. No JavaScript.

#### Package

- `src/ha_archive_search/__init__.py`: minimal public surface — `Match`, `SearchResult`, `main`, `__version__`.
- `pyproject.toml`: installable package with entry point `ha-archive-search = ha_archive_search.engine:main`.

#### Docker

- `docker/Dockerfile`: Python 3.11-slim image with ripgrep installed. Built via `pip install .`, served via `python3 -m ha_archive_search.webapp`.
- `docker/docker-compose.yml`: single-service stack, `versions/` mounted read-only. `HA_SEARCH_CLI` points to the installed entry point `/usr/local/bin/ha-archive-search`.

#### Documentation

- `README.md`: project overview, philosophy, integration contract, architecture, features, deployment.
- `docs/vision_domaine.md`: domain vision — invariants, architecture by phase, security surface, non-goals.
- `docs/contrat_moteur_cli.md`: CLI engine contract — backend, version resolution, perimeter guards, output format, exit codes.
- `docs/contrat_webapp.md`: webapp contract — routes, form validation, Markdown export, UI invariants, Docker boundary. Includes Synology DSM/ACL deployment note.