# ha-archive-search

Infrastructure-side search engine for archived Home Assistant versions.

`ha-archive-search` is a search and exploration toolkit designed for long-lived Home Assistant archives stored outside Home Assistant itself.

The project provides:

- a filesystem search engine;
- a CLI search interface;
- a lightweight web application;
- Markdown export capabilities;
- Docker deployment support.

The system is designed to operate on historical Home Assistant snapshots produced and retained on external infrastructure such as NAS systems.

---

## Philosophy

Home Assistant is optimized for real-time automation and operational dashboards.

`ha-archive-search` addresses a different problem:

- historical exploration;
- forensic investigation;
- configuration archaeology;
- long-term auditability;
- large-scale textual search across archived versions.

The search system intentionally runs outside Home Assistant.

---

## Integration contract

`ha-archive-search` operates on archives produced by [`ha-state-archive`](https://github.com/antoinevalentinHA/ha-state-archive).

The integration contract is the archive corpus layout, not a Python API.

The engine expects:

- a `versions/` directory containing extracted Home Assistant snapshots;
- one directory per snapshot;
- snapshot directories named `YYYY-MM-DD_HH-MM_<suffix>`.

Supported file types:

```text
.yaml  .yml  .json  .txt
.j2  .jinja  .jinja2
.md  .py  .js  .ts  .css  .html
```

No direct dependency on `ha-state-archive` Python code exists.

---

## Architecture

```text
Archive corpus
      │
      ▼
Search engine
      │
      ├── CLI interface
      ├── Markdown export
      └── Web application
```

---

## Features

### Current

- recursive filesystem search;
- version-aware archive traversal;
- text-based filtering with documentation scope control;
- Markdown export;
- Docker deployment;
- web interface accessible over LAN and VPN.

### Planned

- indexed search;
- semantic diff navigation;
- archive metadata search;
- MQTT supervision;
- search statistics.

---

## Repository structure

```text
src/        source code
docker/     Dockerfile and Docker Compose configuration
docs/       domain vision and implementation contracts
tests/      contractual test suite
```

Documentation contracts are located in `docs/`.

---

## License

GPL-3.0-only
