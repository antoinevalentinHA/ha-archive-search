# ha-archive-search — Webapp contract

**Domain**: External tooling / Archive search
**Status**: Active
**Parent document**: `vision_domaine.md`
**Sibling document**: `contrat_moteur_cli.md`

---

## Purpose

This contract defines the architecture and security decisions of the `ha-archive-search` web service:

- technical stack;
- network exposure;
- Docker boundary;
- HTTP routes;
- server-side validation;
- engine / presentation separation;
- Markdown export format;
- UI invariants.

This contract is enforceable: any implementation that deviates from a point here must either be corrected or produce an explicit amendment.

---

## Position in the architecture

```text
ha-archive-search (vision)
  └── Phase 1 — CLI backend engine
        └── engine.py
  └── Phase 2 — Docker webapp              ← THIS CONTRACT
        └── official consumer of the CLI engine
```

The webapp is a presentation layer. It orchestrates, displays, and encapsulates. It makes no decisions and reimplements no search logic.

---

## Invariants

Inherited from the parent contract. Restated here because they govern all technical decisions below.

- **Read-only**: the service never modifies extracted versions or the archive corpus. No write to the host filesystem, including for exports.
- **No free shell**: the user query is never interpreted as a system command.
- **No public exposure**: LAN or VPN only.
- **Server-side bounded results**: bounds are enforced by the CLI engine, never delegated to the web client.
- **Engine authority**: the webapp never reimplements grep logic. All search passes through `engine.py` via `subprocess`. The export does not interpret, aggregate, or reformat the engine stdout.

---

## Technical stack

| Element       | Technology                        |
|---------------|-----------------------------------|
| Web backend   | Flask                             |
| Runtime       | Python 3.11+                      |
| Containerization | Docker                         |
| Search        | delegated to `engine.py`          |
| Frontend      | Server-rendered HTML, no client JS |
| Deployment    | Docker Compose                    |

---

## Docker boundary

### Service name

```text
ha_archive_search_web
```

### Mounted volumes

| Host path          | Container path      | Mode  |
|--------------------|---------------------|-------|
| `<versions_root>`  | `/versions`         | `:ro` |
| `<path_to_engine>` | `/app/engine.py`    | `:ro` |

No other mounts. The container has no other filesystem access.

### Synology DSM / ACL note

On Synology DSM, ACLs may prevent the container user from reading the mounted `versions/` directory even when the volume is mounted read-only.

If `/versions` is visible but not readable from inside the container, use one of the following approaches:

- mount a directory whose Unix permissions are readable by the container user;
- adjust DSM permissions / ACLs for the archive directory;
- configure the container with an explicit `user: "<uid>:<gid>"` matching an account allowed to read the archive corpus.

The project does not require write access to the archive corpus.

### Environment variables

| Variable                  | Default value      |
|---------------------------|--------------------|
| `HA_SEARCH_VERSIONS_ROOT` | `/versions`        |
| `HA_SEARCH_CLI`           | `/app/engine.py`   |
| `HA_SEARCH_TIMEOUT`       | `15`               |
| `HA_SEARCH_MAX_QUERY_LEN` | `200`              |

### Port

| Parameter        | Value   |
|------------------|---------|
| Host port        | `8099`  |
| Container port   | `8099`  |
| Protocol v1      | HTTP (local only) |
| HTTPS            | out of scope v1   |

HTTP v1 justification: the service is intentionally restricted to controlled LAN and VPN environments. VPN encrypts remote traffic. No application auth, no cookie, no token, no direct internet exposure.

---

## Network exposure

| Access              | Status    |
|---------------------|-----------|
| LAN                 | allowed   |
| VPN                 | allowed   |
| Public internet     | forbidden |
| Public reverse proxy | forbidden |

The host firewall must allow port `8099` only from LAN and VPN.

---

## HTTP routes

| Route     | Method | Role |
|-----------|--------|------|
| `/`       | `GET`  | Empty search form |
| `/search` | `POST` | Search execution + result display |
| `/export` | `POST` | Search execution + Markdown download |
| `/health` | `GET`  | Minimal service status (JSON) |

No `/api/*` route in v1. No redirect-after-POST. Results from `/search` are rendered in the same response as the POST.

### `/health` — response format

```json
{
  "status": "ok",
  "versions_root": "/versions",
  "search_cli": "/app/engine.py",
  "versions_root_exists": true,
  "search_cli_exists": true
}
```

The two `*_exists` fields allow detecting a missing mount without opening a shell session.

---

## Search form

### Exposed fields

| Field          | Type     | Default | Server validation               |
|----------------|----------|---------|---------------------------------|
| `query`        | text     | —       | non-empty, stripped, max 200 chars |
| `context`      | checkbox | off     | boolean                         |
| `latest`       | checkbox | off     | boolean                         |
| `exclude_docs` | checkbox | off     | boolean                         |
| `docs_only`    | checkbox | off     | boolean                         |

### Constraints

- `exclude_docs` and `docs_only` are mutually exclusive → reject 400 if both are checked.
- HTML5 validation (`required`, `maxlength`) improves UX but never constitutes a security boundary. Server-side validation is the authority.

The same fields and constraints apply to both `/search` and `/export`.

---

## HTTP return codes

| Case                              | Code |
|-----------------------------------|------|
| OK result                         | 200  |
| Incompatible options / invalid query | 400 |
| Non-zero engine exit code         | 502  |
| Subprocess timeout                | 504  |

502 and 504 errors are surfaced in the HTML body (error block) and visible in container logs.

For the `/export` route, no file is delivered on error. The response is exclusively HTML.

---

## Engine integration

The engine is invoked exclusively via `subprocess.run()`, without `shell=True`.

The user query is passed as a list argument, never concatenated into a command string.

The subprocess timeout is `HA_SEARCH_TIMEOUT` seconds (default: 15 s).

The service is single-worker (Flask development server, `CMD python3 /app/app.py`). Internal threading lock is valid in this context. Any migration to a multi-worker server (e.g. Gunicorn) requires an inter-process lock or a stateless strategy.

The `/search` and `/export` routes share strictly the same invocation mode: same flags, same parameters, same guards. Only stdout handling differs (HTML display vs. Markdown encapsulation).

---

## `/export` route

### Role

Encapsulate the exact CLI engine stdout in a minimal downloadable Markdown document.

### Principle

`/export` reimplements no search logic. It:

1. validates form parameters using the same rules as `/search`;
2. invokes `engine.py` via `subprocess.run()` with the same flags as `/search`;
3. encapsulates stdout in a Markdown envelope;
4. returns the file to the browser as an attachment.

The webapp does not interpret, parse, or reformat the engine stdout. It encapsulates it.

### Output format

Structured Markdown derived from the engine compact stdout via `parse_compact_output()`.

Top-level skeleton:

- `# ha-archive-search — Results`
- `## Query` — block listing query term, mode, version flags, documentation scope, export date.
- `## Summary` — block listing result count, version count, duration. **Always present**: if the engine footer is not parsable, the block is emitted with a single diagnostic line `- Summary parsing: ` `` `failed` `` instead of silently disappearing.
- `## Results` — hierarchy `### <version>` → `#### <path> — N occurrence(s)` → bullet list `- **L<line>** — <content>`.
- `--- Export generated by ha-archive-search v<version>`.

Special cases:

- Empty result set: `## Results` contains `_No results._`. `## Summary` is rendered nominally if the engine emits a zero-result footer; otherwise it shows `Summary parsing: failed`.
- Context mode: `## Results` contains a raw fenced `text` block with the engine stdout. `## Summary` parsing is attempted in isolation; if `SUMMARY_RE` matches a footer line, the block is rendered nominally; otherwise it shows `Summary parsing: failed`.
- Engine footer wording drift: `Summary parsing: failed` is the explicit signal. No silent degradation.

All version names, paths and hit contents are wrapped in adaptive inline code fences (`markdown_inline_code()`) to neutralize Markdown-sensitive characters present in YAML/Python/HTML payloads.

The hit content is **preserved without semantic transformation**: the substring captured by `COMPACT_LINE_RE` is inserted as-is into the rendered output, with adaptive Markdown escaping applied at the encapsulation boundary only. No trimming, no case normalization, no whitespace folding, no semantic enrichment. The rendered Markdown is not byte-equivalent to the engine stdout (encapsulation adds backticks and padding), but the textual payload of each hit is identical.

### File naming

Format:

```text
ha_archive_search_<slug>_<YYYY-MM-DD_HH-MM>.md
```

Slugification rule for `<query>`:

- convert to lowercase;
- allowed characters: `[a-z0-9_-]`;
- any other character replaced by `_`;
- consecutive `_` compressed;
- leading and trailing `_` stripped;
- hard limit: 64 characters maximum;
- if slug is empty after cleaning: `query`.

The slug is ASCII-only by construction.

### HTTP headers

```text
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename="ha_archive_search_<slug>_<timestamp>.md"
```

No streaming `Content-Length` header. The file is bounded in size by the engine ceilings (max 2000 results) and generated in memory before sending.

### HTTP codes — specific behavior

| Case                              | Code | Delivery          |
|-----------------------------------|------|-------------------|
| OK result                         | 200  | `.md` file        |
| Incompatible options / invalid query | 400 | inline HTML message |
| Non-zero engine exit code         | 502  | inline HTML message |
| Subprocess timeout                | 504  | inline HTML message |

No file is delivered on error, including timeout: a silently truncated export would violate the *bounded results* invariant by presenting a partial document as a valid archive.

Partial success with engine-signaled truncation (`results truncated: N displayed out of M` in the engine footer): the file **is** delivered. Truncation is explicitly carried by the engine in the `text` block and remains readable in the export. No special handling on the webapp side.

### Implementation note: ANSI

The CLI engine disables ANSI coloring when `stdout` is not a TTY (`sys.stdout.isatty()`). The stdout captured by `subprocess.run(..., capture_output=True)` is by construction non-TTY. The received content is monochrome; no ANSI sanitization is required on the export side.

### Preserved invariants

- **Read-only**: no file is written to the host. Markdown is generated in memory and transmitted in the HTTP response.
- **Engine authority**: `/export` uses exactly the same parameters and invocation mode as `/search`. No grep logic is duplicated.
- **Server-side bounds**: engine ceilings (results, context, duration) apply in full. The export bypasses no guard.
- **No free shell**: the user query is passed to the engine via `subprocess.run(..., shell=False)`, as an argument list.
- **No persistent state**: no export history, no cache, no storage.

### Consistency with the CLI engine contract

The CLI engine contract lists among its non-goals: "structured Markdown export". This non-goal applies to the **engine** — the engine never emits structured Markdown.

The webapp Markdown export, since v0.3.0, is structured. The structuring is performed by the **presentation layer**, by parsing the engine's compact stdout via `parse_compact_output()`. The parser produces a typed immutable model (`ParsedResults`) consumed by both the HTML and Markdown renderers. No structured output format is required from the engine.

Renderer boundary:

- **Admitted**: deterministic structural aggregation derived from information already present in the stdout — grouping by version, grouping by file, per-file occurrence count, footer summary extraction, Markdown-safe encapsulation.
- **Forbidden**: any form of semantic or historical inference — classification, ranking, filtering, multi-version correlation, first-seen / last-seen tracking, diff computation. Such capabilities, if introduced, belong to a separate intelligence layer above the typed model (out of scope for v0.3.0, see `vision_domaine.md`).

---

## UI invariants

### The UI is not the source of truth

The UI presents, groups, structures, and improves readability. It does not recompute states, does not interpret business contracts, and does not reconstruct domain dependencies.

The text produced by the CLI engine is the truth. The UI displays it; it does not parse it. The export encapsulates it; it does not rewrite it.

### Result display

Results from `/search` are rendered in a `<pre>` block with the raw engine output. No re-parsing, no structured HTML reconstruction of search content in v1.

### Error handling

| Case                    | Display |
|-------------------------|---------|
| Empty query             | Inline message, immediate refusal |
| Incompatible options    | Inline message, immediate refusal |
| Timeout                 | "Search too long (> N s)" |
| Non-zero exit code      | stderr content in error block |
| `versions/` inaccessible | Handled by engine → captured stderr |

No stack trace exposed to the user.

---

## Forbidden perimeter

The service must never access:

- host system internals;
- Docker runtime;
- `/etc`, `/proc`, `/root`;
- raw backups;
- secrets or credentials.

---

## Logs

Logs go exclusively to Docker stdout/stderr.

```bash
docker logs ha_archive_search_web
```

No host `logs/` directory in v1. No application write to the host.

---

## v1 non-goals

- application authentication;
- HTTPS;
- public JSON API;
- search history;
- export history;
- host storage of exports;
- PDF, DOCX, or ZIP export;
- HTML export;
- scheduled export generation;
- historical intelligence (first seen / last seen / multi-version presence) — handled by a separate future layer above the typed model, not by the webapp or the engine;
- file editing;
- free filesystem browsing;
- remote terminal;
- cache;
- inverted index;
- graphical cross-version comparison.

---

## Governance

Any extension increasing the network surface, privileges, execution capabilities, WAN exposure, or write capabilities must be subject to an explicit security review and an amendment to this contract.

---

## Amendments

### v1.0

Initial creation:

- Flask/Docker service on port 8099;
- LAN/VPN access validated;
- `:ro` mounts for `versions/` and `engine.py` active;
- HTTP 502/504 on engine errors;
- server-side validation active.

### v1.1

Addition of `POST /export` route:

- minimal Markdown envelope around the exact engine stdout;
- fields identical to `/search`;
- same HTTP codes, same invariants;
- no host filesystem write;
- no grep logic duplicated;
- inter-contract consistency preserved (export remains unstructured; the CLI engine explicitly excludes structured export).

Additional clarifications:

- v1 non-goals enriched (structured export, PDF/DOCX/ZIP export, HTML export, export history, scheduled generation, host storage of exports);
- explicit statement that `/search` and `/export` share strictly the same engine invocation mode.

### v0.3.0

Amendment of the `/export` section, with broader internal model implications:

- Markdown export becomes **structured**: hierarchy `## Query` / `## Summary` / `## Results` with per-version, per-file grouping.
- The engine `compact` stdout is parsed by `parse_compact_output()`, now shared with the HTML renderer (since v0.2.0) and producing a typed immutable model `ParsedResults` (frozen dataclasses).
- `## Summary` is **always emitted**: nominal content when the footer is parsable, explicit `Summary parsing: failed` diagnostic line otherwise. No silent degradation.
- Context mode preserves a raw fenced fallback under `## Results`; `## Summary` follows the same diagnostic rule.
- Engine authority preserved: no CLI flag change, no new engine output mode, no grep logic added to the webapp.
- Renderer doctrine reformulated: structural aggregation (grouping, counting per file, footer extraction) is admitted; semantic or historical inference (classification, correlation, first-seen / last-seen, diff) remains forbidden.
- v1 non-goal "structured export (by version / file / match)" removed.
- "historical intelligence" remains explicitly out of scope.
