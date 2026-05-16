# ha-archive-search — CLI engine contract

**Domain**: External tooling / Archive search
**Status**: Active — implemented and validated
**Nominal backend**: ripgrep (`rg`)
**Parent document**: `vision_domaine.md`
**Sibling document**: `contrat_webapp.md`

---

## Purpose

This contract defines the implementation decisions of the CLI engine (`engine.py`):

- search backend;
- internal structure;
- version resolution;
- perimeter guards;
- result bounds;
- output format;
- CLI interface.

This contract is enforceable: any implementation that deviates from a point here must either be corrected or produce an explicit amendment.

---

## Position in the architecture

```text
ha-archive-search (vision)
  └── Phase 1 — CLI backend engine       ← THIS CONTRACT
        └── engine.py
  └── Phase 2 — Docker webapp
        └── official consumer of the CLI engine
```

Phase 1 is strictly a backend engine. It is not a user interface. It validates filtering logic, query grammar, and result bounds before packaging as a Phase 2 service.

---

## Invariants

Inherited from the parent contract. Restated here because they govern all technical decisions below.

- **Read-only**: no write to `versions/`, to Home Assistant, or to the archive pipeline.
- **Bounded perimeter**: strict confinement to `versions/`. Verified at every execution.
- **No free shell**: the query is never interpreted as a system command.
- **No public exposure**: Phase 1 is a local tool only.
- **Bounded results**: result count, context depth, and duration are server-enforced hard limits.
- **Engine authority**: the CLI engine remains the functional authority. The webapp never reimplements search logic. All search passes through the engine. No grep logic is duplicated on the Flask side.

---

## Search backend

### Doctrine

The backend is an **internal implementation detail**, not a user-facing feature.

| Backend        | Status                      |
|----------------|-----------------------------|
| `ripgrep` (`rg`) | nominal                   |
| GNU `grep`     | compatibility fallback      |

### Automatic selection

At startup:

- detect `rg` in `PATH`;
- if present → nominal backend;
- if absent → fallback to `grep` with an **explicit warning on stderr**:

```text
[ha-archive-search] warning: ripgrep unavailable, grep fallback activated
```

The warning is not suppressible. It documents the deviation from the nominal backend.

### No user flag

The contract explicitly excludes any flag such as `--backend rg|grep`:

- no unnecessary CLI surface;
- no user/implementation coupling;
- no permanent debug API.

Functional behavior must be **identical** between both backends. Any observable functional difference is a bug in the adapter, not a feature.

---

## Script architecture

### Structure

```python
engine.py
  │
  ├── main()
  │     ├── parse_args()
  │     ├── select_backend()           ← rg or grep
  │     ├── resolve_versions()         ← --latest / --version / --all-versions
  │     ├── build_path_filters()       ← --exclude-docs / --docs-only
  │     ├── enforce_perimeter()        ← invariant: paths ⊂ versions/
  │     ├── run_search()               ← UNIQUE subprocess boundary
  │     ├── format_output()            ← compact / context
  │     └── print_footer()             ← counters + truncation
  │
  └── constants
        ├── VERSIONS_ROOT
        ├── EXTENSIONS
        ├── EXCLUDED_DIRS
        └── LIMITS
```

### Principles

- **Single-file** in Phase 1.
- **No class**, no framework. Pure functions, data flowing through parameters and return values.
- **No mutable global state**.
- **`run_search()` is the only function that invokes `subprocess`**. It is the unique boundary toward the system and the unique point where the *no free shell* invariant is technically enforced.
- **`enforce_perimeter()` is the guard for the *bounded perimeter* invariant**. Called after `resolve_versions()`, before `run_search()`. No path exits it without having been validated.

---

## Version resolution

### Expected naming format

```text
YYYY-MM-DD_HH-MM_<free suffix>
```

Valid examples:

```text
2026-05-08_08-39_HomeAssistant_v2024.5_abc123
2026-05-08_12-00
2026-05-08_18-45_post_changelog
```

Only the **ISO prefix `YYYY-MM-DD_HH-MM`** is part of the contract. The suffix is free. Lexicographic sorting on this prefix is strictly equivalent to chronological sorting: the engine must not depend on datetime parsing for version ordering.

### Three exclusive flags

| Flag                  | Behavior |
|-----------------------|----------|
| `--latest`            | latest version (descending lexicographic sort, first element) |
| `--version <name>`    | version designated by unambiguous prefix |
| `--all-versions`      | all versions, chronological order |

### Exclusivity rule

| Case          | Behavior |
|---------------|----------|
| No flag       | `--latest` implicit |
| One flag      | OK |
| Multiple flags | immediate error, non-zero exit |

### `--version <name>` resolution

The value passed is treated as a **prefix**. The engine searches `versions/` directories whose name starts with this value.

| Case               | Behavior |
|--------------------|----------|
| 1 directory match  | OK, version selected |
| 0 directory match  | explicit error |
| >1 directory match | explicit error + list of matches |

No fuzzy matching. No heuristic. Deterministic prefix only.

### Error behaviors

- `versions/` absent → clear error, non-zero exit.
- `versions/` empty → clear error, non-zero exit.
- No version matches `--version` → list of first 10 available versions + `and N more` if exceeded.

No user-visible stack trace. No silent fallback.

---

## Perimeter and guards

### `enforce_perimeter()`

Guard function, called systematically before any read.

For each resolved path:

1. apply `os.path.realpath()` (symlink and `..` resolution);
2. verify the real path starts with `realpath(VERSIONS_ROOT)`;
3. if not → immediate exception, **no fallback**.

### Extension filtering

```text
.yaml  .yml  .json  .txt
.j2  .jinja  .jinja2
.md  .py  .js  .ts  .css  .html
```

Implementation:

- `rg` backend → `--type-add` or `--glob`;
- `grep` backend → `--include='*.<ext>'`.

### Directory exclusion (defense in depth)

```text
.storage/
.git/
__pycache__/
deps/
node_modules/
temp/
logs/
```

These directories are not expected to be present in `versions/` (upstream pipeline filtering). Explicit exclusion is a redundant guarantee.

### Documentation scope filtering

| Mode | Behavior |
|------|----------|
| (default) | includes the documentation directory |
| `--exclude-docs` | excludes the documentation directory |
| `--docs-only` | searches **only** in the documentation directory |

`--exclude-docs` and `--docs-only` are **mutually exclusive**. If both are passed → immediate error, no implicit priority.

---

## Bounds

| Parameter       | Default value | Hard ceiling |
|-----------------|---------------|--------------|
| Result count    | 200           | 2000         |
| Context (lines) | 5             | 50           |
| Query timeout   | 10 s          | 30 s         |

- All bounds are enforced **server-side**, never delegated to the client.
- A user value above the ceiling is clamped to the ceiling and reported in the footer.
- Timeout is enforced via `subprocess.run(..., timeout=...)`. On expiry → explicit error; no partial result must be presented as complete.

### Truncation behavior

```text
results truncated: 200 displayed out of 1247  •  duration 0.32 s
```

---

## Output format

### Compact mode

Fixed format: `[version] relative_path:line: content`

```text
[2026-05-08_08-39_HomeAssistant_v2024.5_abc123] automations/heating/control.yaml:42: condition: state sensor.temperature_outdoor
[2026-05-08_08-39_HomeAssistant_v2024.5_abc123] automations/heating/control.yaml:78:   - sensor.temperature_outdoor
[2026-04-15_18-12_HomeAssistant_v2024.4]        automations/heating/control.yaml:42: condition: state sensor.temperature_outdoor
```

- Path **relative** to the version root, never absolute.
- Version in brackets at line start (grep-able, awk-able).
- `:` after line number (editor-compatible: `vim path:42`).

### Context mode

```text
═══════════════════════════════════════════════════════════
[2026-05-08_08-39_HomeAssistant_v2024.5_abc123] automations/heating/control.yaml:42
───────────────────────────────────────────────────────────
  37  - alias: Heating regulation
  38    trigger:
  39      - platform: state
  40        entity_id: sensor.temperature_outdoor
  41    condition:
> 42      - condition: state
  43        entity: sensor.temperature_outdoor
  44        state: 'on'
  45    action:
  46      - service: climate.set_temperature
  47        target:
═══════════════════════════════════════════════════════════
```

- Thick `═` separator between matches.
- Thin `─` separator between header and content.
- Match line prefixed with `> ` (one character + space, clean copy/paste).
- Line numbers right-aligned on 4 digits.

### Mandatory footer

Always present, even on 0 results.

```text
───────────────────────────────────────────────────────────
3 results across 2 versions  •  duration 0.18 s
```

```text
───────────────────────────────────────────────────────────
0 results across 1 version  •  duration 0.04 s
```

```text
───────────────────────────────────────────────────────────
results truncated: 200 displayed out of 1247  •  duration 0.32 s
```

The footer distinguishes *no match* from *silently failing engine*.

### Color

- `stdout` is a TTY → colored output.
- `stdout` is redirected (file, pipe) → monochrome output.
- Automatic detection via `sys.stdout.isatty()`. No user flag.

---

## CLI interface

### Synopsis

```text
engine.py --query <text> [version options] [filter options] [output options]
```

### Fixed options

```text
--query <text>           query (required)

# Version selection (mutually exclusive, default: --latest)
--latest
--version <prefix>
--all-versions

# Documentation scope (mutually exclusive)
--exclude-docs
--docs-only

# Search
--case-sensitive
--regex

# Output
--mode compact|context   default: compact
--context N              default: 5, ceiling: 50

# Bounds
--max-results N          default: 200, ceiling: 2000
```

### Default behaviors

| Without flag          | Behavior |
|-----------------------|----------|
| No version flag       | `--latest` |
| No docs flag          | documentation included |
| `--mode` not specified | `compact` |
| `--context` not specified | 5 lines (context mode only) |
| `--case-sensitive` not specified | case-insensitive search |
| `--regex` not specified | literal text search |

### Exit codes

| Code | Meaning |
|------|---------|
| 0    | OK (with or without results) |
| 1    | usage error (incompatible flags, invalid value) |
| 2    | environment error (`versions/` absent, critical backend unavailable) |
| 3    | query timeout |

---

## Required qualities

- **readable** — a reviewer must be able to read it entirely in one session;
- **auditable** — every guard and every bound must be quickly locatable;
- **single-file** in Phase 1;
- **no framework**;
- **explicit responsibilities** — one function, one responsibility;
- **no mutable global state**;
- **no third-party Python dependency** (stdlib only).

---

## Non-goals of the CLI engine

Out of scope for the CLI engine itself:

- JSON output;
- graphical or web interface;
- Docker service;
- remote access (HTTP, automated SSH, etc.);
- result cache;
- inverted index;
- usage statistics;
- cross-version comparison (integrated diff);
- structured Markdown export.

These belong to Phase 2 or future evolutions and must not pre-contaminate the engine architecture.

---

## Phase 2 compatibility

Design constraints validated for Phase 2 integration without breaking changes:

- pure and importable functions — the webapp invokes the engine without coupling;
- simple data structures (dict, list, tuple) — no proprietary serialization;
- business logic decoupled from text formatting — the webapp consumes stdout without parsing terminal rendering;
- CLI API preserved integrally — `subprocess` on the Flask side calls exactly the same flags.

Evolutions remaining compatible without breaking the API:

- adding `--output-format text|json` flag (text remains default);
- adding path filters (`--include-path`, `--exclude-path`);
- pagination (`--offset N`).

---

## Backend implementation notes

- **Null-separated parsing**: output normalized by `\0` separator for unambiguous parsing on paths containing `:` or `-`.
  - rg: `--null`
  - grep: `-Z`
- **Command discipline**: all flags and filters before the pattern, pattern via `--regexp` (rg) or `-e` (grep), root in last position. Canonical GNU form.
