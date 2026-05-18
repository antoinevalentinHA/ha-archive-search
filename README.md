# ha-archive-search

Infrastructure-side search engine for archived Home Assistant versions.

`ha-archive-search` is a search and exploration toolkit designed for long-lived Home Assistant archives stored outside Home Assistant itself.

The project provides:

- a corpus search engine;
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

The search system intentionally operates outside Home Assistant infrastructure.

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
- Docker deployment.

### Planned

- indexed search;
- semantic diff navigation;
- archive metadata search;
- MQTT supervision;
- search statistics.

---

## Deployment

The web application runs as a Docker container on the same infrastructure as the archive corpus (typically a NAS system). It is accessible over LAN and VPN. No public exposure is supported or intended.

---

## Synology DSM deployment

A dedicated Synology compose example is provided:

```text
docker/docker-compose.synology.yml
```

### Why a Synology-specific compose file exists

Many Synology DSM shared folders use restrictive ACLs which prevent
non-root container users from traversing mounted paths.

Typical error:

```text
[ha-archive-search] perimeter error:
[Errno 13] Permission denied: '/versions'
```

The Synology compose example explicitly runs the container as root:

```yaml
user: "0:0"
```

This avoids traversal failures on DSM-mounted shared folders.

Advanced users may replace this with a custom UID:GID mapping.

---

## Repository structure

```text
src/        source code
docker/     Dockerfile and Docker Compose configuration
docs/       domain vision and implementation contracts
```

Documentation contracts are located in `docs/`.

---

## License

GPL-3.0-only
