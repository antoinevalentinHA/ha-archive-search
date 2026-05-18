# ha-archive-search — Domain vision

**Domain**: External tooling / Archive search
**Status**: Active
**Child documents**:
- `contrat_webapp.md` — Flask/Docker service contract
- `contrat_moteur_cli.md` — CLI engine contract

---

## Purpose

`ha-archive-search` provides an on-demand search engine over extracted Home Assistant versions produced by an external archive pipeline.

The system is designed to replace ad-hoc local search scripts and enables consultation from:

- desktop;
- mobile;
- web browser;
- local network or VPN.

`ha-archive-search` is not limited to Home Assistant entity search. It is a textual search and audit engine designed for archived configuration corpora.

---

## Data source

The search engine operates exclusively on a `versions/` directory containing extracted Home Assistant snapshots.

This scope is assumed to be pre-filtered by the upstream archive pipeline: `versions/` contains only configuration and state files — no raw backups, no encrypted archives, no SQLite databases, no runtime logs.

`ha-archive-search` inherits this filtering. It does not redefine it, but it commits to never operating outside this perimeter.

---

## Architectural principle

```text
Home Assistant
  → encrypted backups
  → external archive pipeline
  → extracted versions
  → ha-archive-search
  → browser (desktop / mobile)
```

`ha-archive-search` belongs exclusively to the tooling and audit layer.

The engine produces no Home Assistant decisions.

---

## Separation of responsibilities

| Component              | Responsibility                          |
|------------------------|-----------------------------------------|
| Archive pipeline       | Backup extraction and retention         |
| Diff engine            | Inter-version diff generation           |
| CLI engine             | Bounded search engine                   |
| Flask UI               | HTML presentation and Markdown export   |
| Containerized execution environment | Runtime boundary                        |
| VPN / LAN              | Network access control                  |

The web layer makes no decisions, parses no business logic, and never modifies data. It orchestrates, presents, and encapsulates. The CLI engine remains the functional authority.

---

## Invariants

Hard contracts of the domain. All evolutions must preserve them.

- **Read-only**: `ha-archive-search` never modifies extracted versions. This invariant also applies to Markdown export, which is generated in memory and never written to the archive.
- **Bounded perimeter**: search is strictly confined to the `versions/` directory. No path outside this root is readable.
- **No free shell**: the user submits a query, never a command. The query is never interpreted as a system command.
- **No public exposure**: LAN or VPN access only. No public reverse proxy, no external exposure.
- **Bounded results**: result count, context depth, and search duration are server-enforced hard limits, non-negotiable by the client.
- **Containerized execution environment**: the web service mounts `versions/` and the CLI engine read-only and has no other filesystem access.
- **Engine authority**: the webapp never reimplements search logic. All search passes through the CLI engine. The webapp may parse compact stdout into a typed presentation model for structural rendering, without re-running search logic, filtering results, ranking matches, or inferring domain meaning.

---

## Architecture by phase

### Phase 1 — CLI backend engine

- Internal tool only.
- Not intended for daily or mobile use.
- Usage: maintenance, engine validation, punctual audits.

Phase 1 validates filtering logic, query grammar, and result bounds before packaging as a service.

### Phase 2 — Web application

- Real user interface.
- Local Docker service.
- Accessible from desktop and mobile, over LAN or VPN.
- This is the actual target usage of the domain.

Phase 1 is not a user interface. All user-facing consultation goes through Phase 2.

---

## v1 features

### Search

- plain text search;
- case-insensitive by default;
- strict case option;
- regex option;
- search in the latest version;
- search in a specific version;
- multi-version search.

### Documentation scope control

A documentation directory at the root of each version can be included, excluded, or exclusively targeted.

```text
normal mode    → includes documentation
--exclude-docs → excludes the documentation directory
--docs-only    → searches only in the documentation directory
```

`--exclude-docs` is intended for runtime/configuration searches to avoid documentation noise.

`--docs-only` is intended for documentation audits, contract reviews, and changelog searches.

### Markdown export

Search results can be downloaded as a Markdown document.

```text
interactive search  → HTML display (/search)
markdown export     → .md download (/export)
```

The Markdown export produces a **structured presentation** derived from the CLI engine compact stdout: a parameter header, a typed summary, grouped results by version and file, and an identification footer. This structuring is presentational only and does not change search semantics.

Use cases:

- local retention of a complex search;
- sharing a clean investigation;
- archiving a punctual audit;
- exploiting results outside the web interface.

---

## Queries

Queries are free text. They may contain:

```text
/  \  :  .  -  _  #  ()  []  {}
```

Valid examples:

```text
sensor.temperature_outdoor
mdi:router-wireless
rgba(76, 175, 80, 0.2)
/volume1/archive/versions/
```

The query grammar is owned by the engine layer. Shell injection is prevented by the engine (`subprocess` without `shell=True`, query passed as parameter, never concatenated).

---

## File perimeter

### Searched extensions

```text
.yaml  .yml  .json  .txt
.j2  .jinja  .jinja2
.md  .py  .js  .ts  .css  .html
```

Binary files are ignored.

### Excluded directories (defense in depth)

```text
.storage/
.git/
__pycache__/
deps/
node_modules/
temp/
logs/
```

These directories are not expected to be present in `versions/` (upstream pipeline filtering). Their exclusion by the search engine is a redundant guarantee.

---

## Result bounds

| Parameter       | Default value | Hard ceiling |
|-----------------|---------------|--------------|
| Result count    | 200           | 2000         |
| Context (lines) | 5             | 50           |
| Query timeout   | 10 s          | 30 s         |

When results are truncated, the output indicates it explicitly. This indication is produced by the CLI engine footer and appears as-is in the Markdown export.

---

## Security

### Exposure surface

| Access          | Status    |
|-----------------|-----------|
| LAN             | allowed   |
| VPN             | allowed   |
| Public internet | forbidden |
| Public reverse proxy | forbidden |

### Engine obligations

- all searches are executed via secure parameters (`subprocess` without shell);
- the user query is never concatenated into a command line;
- all paths are confined to the `versions/` root (membership verified before read);
- result and timeout bounds are enforced server-side, never client-side.

---

## Non-goals

`ha-archive-search` must never:

- modify Home Assistant;
- modify extracted versions;
- access raw backups;
- expose a remote terminal;
- execute arbitrary commands;
- replace Git;
- replace the upstream archive pipeline.

---

## Future evolutions

- graphical version selection;
- multi-version search with grouping;
- direct link to file or result;
- grep comparison between two versions;
- entity dependency search;
- entity-to-file consumption graph.

Structured Markdown export is now produced by the webapp from the compact engine stdout. A future machine-oriented engine output format (for example JSON or NDJSON) remains possible, but is not required for the current human-readable structured Markdown export.

---

## Typical use cases

- locating an entity;
- auditing a refactor;
- identifying a sensor introduction;
- tracing a dependency;
- reviewing a contract;
- comparing versions;
- locating a helper or a dashboard;
- tracking technical debt;
- archiving an investigation as a Markdown document.
