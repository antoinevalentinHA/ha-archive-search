#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from ha_archive_search._version import __version__

APP_NAME = "ha-archive-search"
VERSIONS_ROOT = Path(os.environ.get("HA_SEARCH_VERSIONS_ROOT", "/versions"))
SEARCH_CLI = Path(os.environ.get("HA_SEARCH_CLI", "/usr/local/bin/ha-archive-search"))
TIMEOUT_SECONDS = int(os.environ.get("HA_SEARCH_TIMEOUT", "15"))
MAX_QUERY_LEN = int(os.environ.get("HA_SEARCH_MAX_QUERY_LEN", "200"))

app = Flask(__name__)

_search_lock = threading.Lock()

SLUG_RE = re.compile(r"[^a-z0-9_-]+")
UNDERSCORE_RE = re.compile(r"_+")

COMPACT_LINE_RE = re.compile(
    r"^\[(?P<version>[^\]]+)\]\s+"
    r"(?P<path>.*?):"
    r"(?P<line>\d+):"
    r"(?P<content>.*)$"
)

# ---------------------------------------------------------------------------
# Footer recognition cascade (v0.3.1).
#
# The engine emits three distinct footer formats (engine.py L726-748):
#   - nominal   : "N results across M versions  •  duration D s"
#   - truncated : "results truncated: N displayed out of at least M  •  duration D s"
#   - timeout   : "query timeout: N partial results (not guaranteed) across M versions  •  duration D s"
#
# The three regex are mutually exclusive by prefix:
#   - nominal   starts with \d+
#   - truncated starts with "results truncated:"
#   - timeout   starts with "query timeout:"
#
# A line matches at most one regex. The cascade order is canonical
# (most frequent first) but the result does not depend on order.
#
# If none match, the footer is genuine engine drift and the summary
# remains None (rendered as "Summary parsing: failed").
# ---------------------------------------------------------------------------

SUMMARY_RE_NOMINAL = re.compile(
    r"^(?P<count>\d+)\s+results?\s+"
    r"across\s+(?P<versions>\d+)\s+versions?\s+"
    r"•\s+duration\s+(?P<duration>[0-9.,]+)\s+s$"
)

SUMMARY_RE_TRUNCATED = re.compile(
    r"^results\s+truncated:\s+"
    r"(?P<count>\d+)\s+displayed\s+"
    r"out\s+of\s+at\s+least\s+(?P<total>\d+)\s+"
    r"•\s+duration\s+(?P<duration>[0-9.,]+)\s+s$"
)

SUMMARY_RE_TIMEOUT = re.compile(
    r"^query\s+timeout:\s+"
    r"(?P<count>\d+)\s+partial\s+results?\s+\(not\s+guaranteed\)\s+"
    r"across\s+(?P<versions>\d+)\s+versions?\s+"
    r"•\s+duration\s+(?P<duration>[0-9.,]+)\s+s$"
)


# ---------------------------------------------------------------------------
# Internal typed model (v0.3.0).
#
# Contract between parse_compact_output() and renderers (HTML / Markdown).
# Frozen dataclasses: structural immutability is part of the contract — the
# renderer cannot mutate by inadvertence.
#
# Tuples (not lists): signal of "structure fixed at construction time",
# aligned with frozen=True.
#
# line: int — line_no was str in v0.2.0 by typing laziness; conversion is
# safe because COMPACT_LINE_RE captures \d+.
#
# duration: str — preserves the exact precision emitted by the engine
# (locale handling via .replace(",", ".")). No float cast that would
# introduce rounding.
#
# This is an internal model exposed for testability only.
# No backward compatibility guarantee before v1.0.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    line: int
    content: str


@dataclass(frozen=True)
class FileResult:
    path: str
    hits: tuple[Hit, ...]


@dataclass(frozen=True)
class VersionResult:
    version: str
    files: tuple[FileResult, ...]


@dataclass(frozen=True)
class Summary:
    """Footer moteur typé (v0.3.1).

    status :
      - "nominal"   : le moteur a terminé normalement, comptes exacts.
      - "truncated" : le moteur a atteint --max-results, comptes partiels,
                      total minoré disponible via `total`.
      - "timeout"   : le moteur a dépassé --timeout, comptes partiels non
                      garantis ("not guaranteed").

    count    : nombre de résultats affichés. Toujours présent.

    total    : "out of at least N". Présent uniquement pour status="truncated".
               None pour nominal et timeout (le moteur ne l'émet pas).

    versions : nombre de versions parcourues. Présent pour nominal et timeout.
               None pour status="truncated" (le moteur ne l'émet pas dans ce
               footer — engine.py L737-742).

    duration : durée en secondes telle qu'émise par le moteur. Toujours
               présente. Locale-aware via .replace(",", ".") préservé de v0.3.0.

    raw_footer : ligne footer brute reçue du moteur. Source de vérité
                 textuelle préservée pour audit. Non exposée dans les rendus
                 v0.3.1 ; champ interne uniquement.
    """
    status: Literal["nominal", "truncated", "timeout"]
    count: int
    total: int | None
    versions: int | None
    duration: str
    raw_footer: str | None = None


@dataclass(frozen=True)
class ParsedResults:
    versions: tuple[VersionResult, ...]
    summary: Summary | None


def now_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def filename_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M")


def slugify_query(query: str) -> str:
    slug = query.lower()
    slug = SLUG_RE.sub("_", slug)
    slug = UNDERSCORE_RE.sub("_", slug)
    slug = slug.strip("_")
    slug = slug[:64].strip("_")
    return slug or "query"


def markdown_inline_code(value: str) -> str:
    """Encapsule value dans une fence backtick inline.

    La fence est choisie pour être strictement plus longue que la plus
    longue séquence de backticks contenue dans value. Si value commence
    ou finit par un backtick, des espaces de garde sont insérés.
    """
    if not value:
        return "``"

    runs = re.findall(r"`+", value)
    max_run = max((len(run) for run in runs), default=0)
    fence = "`" * (max_run + 1) if max_run > 0 else "`"

    pad = " " if (value.startswith("`") or value.endswith("`")) else ""
    return f"{fence}{pad}{value}{pad}{fence}"


def documentation_label(options: dict[str, bool]) -> str:
    if options.get("exclude_docs"):
        return "excluded"
    if options.get("docs_only"):
        return "only"
    return "included"


def bool_label(value: bool) -> str:
    return "yes" if value else "no"


def markdown_fence_for(content: str) -> str:
    runs = re.findall(r"`+", content)
    max_run = max((len(run) for run in runs), default=0)
    return "`" * max(3, max_run + 1)


def _try_match_footer(line: str) -> Summary | None:
    """Tente de reconnaître `line` comme un footer moteur connu.

    Applique la cascade SUMMARY_RE_NOMINAL → SUMMARY_RE_TRUNCATED →
    SUMMARY_RE_TIMEOUT. Les trois regex sont mutuellement exclusives par
    préfixe ; l'ordre est canonique mais le résultat ne dépend pas de l'ordre.

    Retourne :
      - Summary(status="nominal" | "truncated" | "timeout", ...) si reconnu.
      - None si aucune regex ne matche (drift moteur réel).

    raw_footer est toujours renseigné avec la ligne reçue (modulo le rstrip("\\n")
    appliqué en amont par les appelants).
    """
    m = SUMMARY_RE_NOMINAL.fullmatch(line)
    if m:
        return Summary(
            status="nominal",
            count=int(m.group("count")),
            total=None,
            versions=int(m.group("versions")),
            duration=m.group("duration").replace(",", "."),
            raw_footer=line,
        )

    m = SUMMARY_RE_TRUNCATED.fullmatch(line)
    if m:
        return Summary(
            status="truncated",
            count=int(m.group("count")),
            total=int(m.group("total")),
            versions=None,
            duration=m.group("duration").replace(",", "."),
            raw_footer=line,
        )

    m = SUMMARY_RE_TIMEOUT.fullmatch(line)
    if m:
        return Summary(
            status="timeout",
            count=int(m.group("count")),
            total=None,
            versions=int(m.group("versions")),
            duration=m.group("duration").replace(",", "."),
            raw_footer=line,
        )

    return None


def render_markdown_query(query: str, options: dict[str, bool]) -> str:
    """Rend la section ## Query du Markdown export."""
    mode = "context" if options.get("context") else "compact"
    return (
        "## Query\n"
        "\n"
        f"- Term: {markdown_inline_code(query)}\n"
        f"- Mode: {markdown_inline_code(mode)}\n"
        f"- Latest only: {markdown_inline_code(bool_label(options.get('latest', False)))}\n"
        f"- All versions: {markdown_inline_code(bool_label(options.get('all_versions', False)))}\n"
        f"- Documentation: {markdown_inline_code(documentation_label(options))}\n"
        f"- Export date: {markdown_inline_code(now_timestamp())}\n"
        "\n"
    )


def render_markdown_summary(summary: Summary | None) -> str:
    """Rend la section ## Summary, toujours présente.

    summary None → bloc rendu avec ligne diagnostic `- Summary parsing: failed`.
                   Réservé aux cas de drift moteur réel (aucune des trois
                   regex SUMMARY_RE_* ne matche).
    summary présent → bloc rendu selon `status`:
      - "nominal"   : Results / Versions / Duration (Status omis, doctrine
                      "le défaut ne se signale pas").
      - "truncated" : Status / Results (N displayed) / Total (at least M) / Duration.
      - "timeout"   : Status / Results (N partial, not guaranteed) / Versions / Duration.

    Doctrinal : truncated et timeout ne sont plus rétrogradés en
    "Summary parsing: failed". Ce sont des signaux d'intégrité émis par
    le moteur, identifiés et rendus comme tels.
    """
    if summary is None:
        return "## Summary\n\n- Summary parsing: `failed`\n\n"

    if summary.status == "nominal":
        return (
            "## Summary\n"
            "\n"
            f"- Results: {markdown_inline_code(str(summary.count))}\n"
            f"- Versions: {markdown_inline_code(str(summary.versions))}\n"
            f"- Duration: {markdown_inline_code(summary.duration + ' s')}\n"
            "\n"
        )

    if summary.status == "truncated":
        return (
            "## Summary\n"
            "\n"
            f"- Status: {markdown_inline_code('truncated')}\n"
            f"- Results: {markdown_inline_code(str(summary.count) + ' displayed')}\n"
            f"- Total: {markdown_inline_code('at least ' + str(summary.total))}\n"
            f"- Duration: {markdown_inline_code(summary.duration + ' s')}\n"
            "\n"
        )

    if summary.status == "timeout":
        return (
            "## Summary\n"
            "\n"
            f"- Status: {markdown_inline_code('timeout')}\n"
            f"- Results: {markdown_inline_code(str(summary.count) + ' partial (not guaranteed)')}\n"
            f"- Versions: {markdown_inline_code(str(summary.versions))}\n"
            f"- Duration: {markdown_inline_code(summary.duration + ' s')}\n"
            "\n"
        )

    # Défensif : status inattendu (ne devrait pas être atteignable depuis
    # _try_match_footer qui ne produit que les trois statuts ci-dessus).
    return "## Summary\n\n- Summary parsing: `failed`\n\n"


def render_markdown_results(parsed: ParsedResults, fallback_stdout: str) -> str:
    """Rend la section ## Results en Markdown structuré.

    - parsed.versions non vide → hiérarchie version > path > hits.
    - parsed.versions vide + stdout = footer seul (compact zéro-hit)
      OU stdout vide/sentinelle → "_No results._".
    - parsed.versions vide + stdout multi-lignes (mode contexte)
      → code fence brut.

    Arbitrage §3.4 / §11.3 : §3.4 enverrait toute branche "versions vide
    + stdout non vide" sur fence brut. §11.3 attend "_No results._" pour
    le cas "compact zéro-hit avec footer parsé". On résout en utilisant
    la cascade SUMMARY_RE_* comme discriminant : si le stdout entier strip
    est uniquement un footer reconnu (nominal, truncated ou timeout), c'est
    compact zéro-hit → "_No results._". Sinon (stdout multi-lignes typique
    du mode contexte) → fence brut.
    """
    if parsed.versions:
        lines = ["## Results", ""]
        for v in parsed.versions:
            lines.append(f"### {markdown_inline_code(v.version)}")
            lines.append("")
            for f in v.files:
                count = len(f.hits)
                plural = "occurrence" if count == 1 else "occurrences"
                lines.append(f"#### {markdown_inline_code(f.path)} — {count} {plural}")
                lines.append("")
                for hit in f.hits:
                    lines.append(f"- **L{hit.line}** — {markdown_inline_code(hit.content)}")
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    stripped = fallback_stdout.strip()
    if not stripped or stripped == "No results.":
        return "## Results\n\n_No results._\n"
    if _try_match_footer(stripped) is not None:
        # Compact zéro-hit : stdout entier = footer (nominal/truncated/timeout).
        return "## Results\n\n_No results._\n"

    fence = markdown_fence_for(fallback_stdout)
    block = fallback_stdout if fallback_stdout.endswith("\n") else f"{fallback_stdout}\n"
    return f"## Results\n\n{fence}text\n{block}{fence}\n"


def build_markdown_export(query: str, options: dict[str, bool], stdout: str) -> str:
    """Construit le Markdown structuré v0.3.0 pour l'export.

    Mode compact : parse complet du stdout, hiérarchie structurée.
    Mode contexte : pas de parsing structurel, summary best-effort isolé,
    fence brut pour le bloc Results.
    """
    if not options.get("context"):
        parsed = parse_compact_output(stdout)
    else:
        # Mode contexte : extraction best-effort du summary uniquement.
        # Même cascade que parse_compact_output() — symétrie compact/contexte.
        summary: Summary | None = None
        for raw_line in stdout.splitlines():
            candidate = _try_match_footer(raw_line.rstrip("\n"))
            if candidate is not None:
                summary = candidate
                break
        parsed = ParsedResults(versions=(), summary=summary)

    parts = [
        "# ha-archive-search — Results\n",
        "\n",
        render_markdown_query(query, options),
        render_markdown_summary(parsed.summary),
        render_markdown_results(parsed, stdout),
        "\n",
        "---\n",
        f"Export generated by ha-archive-search v{__version__}\n",
    ]
    return "".join(parts)


def bool_from_form(name: str) -> bool:
    return request.form.get(name) == "on"


def validate_form() -> tuple[str, dict[str, bool], str]:
    query = (request.form.get("query") or "").strip()
    if not query:
        return "", {}, "Empty query."
    if len(query) > MAX_QUERY_LEN:
        return "", {}, f"Query too long. Maximum: {MAX_QUERY_LEN} characters."

    options = {
        "context": bool_from_form("context"),
        "latest": bool_from_form("latest"),
        "all_versions": bool_from_form("all_versions"),
        "exclude_docs": bool_from_form("exclude_docs"),
        "docs_only": bool_from_form("docs_only"),
    }

    if options["latest"] and options["all_versions"]:
        return "", {}, "Incompatible options: latest only and all versions."

    if options["exclude_docs"] and options["docs_only"]:
        return "", {}, "Incompatible options: exclude documentation and documentation only."

    return query, options, ""


def build_command(query: str, options: dict[str, bool]) -> list[str]:
    cmd = ["python3", str(SEARCH_CLI), "--query", query]

    if options.get("all_versions"):
        cmd.append("--all-versions")
    elif options.get("latest"):
        cmd.append("--latest")

    if options.get("exclude_docs"):
        cmd.append("--exclude-docs")
    if options.get("docs_only"):
        cmd.append("--docs-only")

    if options.get("context"):
        cmd.extend(["--mode", "context"])
    else:
        cmd.extend(["--mode", "compact"])

    return cmd


def run_search_cli(
    query: str, options: dict[str, bool]
) -> tuple[subprocess.CompletedProcess[str] | None, str, int]:
    if not VERSIONS_ROOT.exists():
        return None, f"Versions directory not accessible: {VERSIONS_ROOT}", 500

    if not SEARCH_CLI.exists():
        return None, f"Search engine not found: {SEARCH_CLI}", 500

    acquired = _search_lock.acquire(blocking=False)
    if not acquired:
        return None, "A search is already in progress. Please retry in a few seconds.", 429

    try:
        result = subprocess.run(
            build_command(query, options),
            timeout=TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            error = result.stderr.strip() or f"Engine returned exit code {result.returncode}."
            return result, error, 502

        return result, "", 200

    except subprocess.TimeoutExpired:
        return None, f"Search too long (>{TIMEOUT_SECONDS} s).", 504

    except Exception:
        return None, "Internal error during search.", 500

    finally:
        _search_lock.release()


def parse_compact_output(output: str) -> ParsedResults:
    """Parse le stdout compact du moteur en structure typée immuable.

    Retourne toujours un ParsedResults.
    - parsed.versions = () si aucun hit parsé (résultat vide ou mode contexte).
    - parsed.summary = None si aucune des trois regex SUMMARY_RE_NOMINAL /
      SUMMARY_RE_TRUNCATED / SUMMARY_RE_TIMEOUT ne matche (drift moteur réel).
      Les cas truncated et timeout sont reconnus depuis v0.3.1 et produisent
      un Summary typé avec le statut correspondant — ils ne sont plus
      rétrogradés en "Summary parsing: failed".
    """
    versions_acc: dict[str, dict[str, list[Hit]]] = {}
    summary: Summary | None = None

    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")

        candidate = _try_match_footer(line)
        if candidate is not None:
            summary = candidate
            continue

        if not line or line.startswith("─") or line.startswith("═"):
            continue

        m = COMPACT_LINE_RE.match(line)
        if not m:
            continue

        version = m.group("version")
        path = m.group("path")
        line_no = int(m.group("line"))
        content = m.group("content")

        versions_acc.setdefault(version, {}).setdefault(path, []).append(
            Hit(line=line_no, content=content)
        )

    versions_typed = tuple(
        VersionResult(
            version=ver,
            files=tuple(
                FileResult(path=p, hits=tuple(hits))
                for p, hits in files.items()
            ),
        )
        for ver, files in versions_acc.items()
    )

    return ParsedResults(versions=versions_typed, summary=summary)


def empty_template(**kwargs):
    defaults = {
        "app_name": APP_NAME,
        "query": "",
        "output": "",
        "error": "",
        "parsed": ParsedResults(versions=(), summary=None),
        "context": False,
        "latest": False,
        "all_versions": False,
        "exclude_docs": False,
        "docs_only": False,
    }
    defaults.update(kwargs)
    return render_template("index.html", **defaults)


@app.get("/")
def index():
    return empty_template()


@app.get("/search")
def search_get():
    return redirect(url_for("index"))


@app.post("/search")
def search():
    query, options, validation_error = validate_form()

    if validation_error:
        return empty_template(
            query=query,
            output="",
            error=validation_error,
            **{k: bool(options.get(k, False)) for k in ("context", "latest", "all_versions", "exclude_docs", "docs_only")},
        ), 400

    result, error, status_code = run_search_cli(query, options)
    if error:
        return empty_template(query=query, output="", error=error, **options), status_code

    output = result.stdout.strip() or "No results."

    parsed = ParsedResults(versions=(), summary=None)
    if not options.get("context"):
        parsed = parse_compact_output(output)

    return empty_template(
        query=query,
        output=output,
        error="",
        parsed=parsed,
        **options,
    )


@app.get("/export")
def export_get():
    return redirect(url_for("index"))


@app.post("/export")
def export_markdown():
    query, options, validation_error = validate_form()

    if validation_error:
        return empty_template(
            query=query,
            output="",
            error=validation_error,
            **{k: bool(options.get(k, False)) for k in ("context", "latest", "all_versions", "exclude_docs", "docs_only")},
        ), 400

    result, error, status_code = run_search_cli(query, options)
    if error:
        return empty_template(query=query, output="", error=error, **options), status_code

    markdown = build_markdown_export(query, options, result.stdout)
    filename = f"ha_archive_search_{slugify_query(query)}_{filename_timestamp()}.md"

    return Response(
        markdown,
        status=200,
        headers={
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "versions_root": str(VERSIONS_ROOT),
        "search_cli": str(SEARCH_CLI),
        "versions_root_exists": VERSIONS_ROOT.exists(),
        "search_cli_exists": SEARCH_CLI.exists(),
    })


def main() -> None:
    app.run(host="0.0.0.0", port=8099, debug=False)


if __name__ == "__main__":
    main()
