#!/usr/bin/env python3
# ==========================================================
# ha-archive-search — CLI search engine
# ----------------------------------------------------------
# Phase 1 — CLI backend engine
#
# Invariants
#   - Read-only
#   - Perimeter strictly bounded to VERSIONS_ROOT
#   - No free shell
#   - Server-side bounded results
#   - Nominal backend: ripgrep, fallback: GNU grep
# ==========================================================

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# ----------------------------------------------------------
# Constants
# ----------------------------------------------------------

VERSIONS_ROOT = Path(
    os.environ.get(
        "HA_SEARCH_VERSIONS_ROOT",
        "/versions",
    )
)

DOCS_DIR = os.environ.get("HA_SEARCH_DOCS_DIR", "docs")

RG_CANDIDATES = ["rg"]
GREP_CANDIDATES = ["/bin/grep", "grep"]

EXTENSIONS = [
    ".yaml", ".yml", ".json", ".txt",
    ".j2", ".jinja", ".jinja2",
    ".md", ".py", ".js", ".ts", ".css", ".html",
]

EXCLUDED_DIRS = [
    ".storage", ".git", "__pycache__",
    "deps", "node_modules", "temp", "logs",
]

DEFAULT_MAX_RESULTS = 200
HARD_MAX_RESULTS = 2000

DEFAULT_CONTEXT = 5
HARD_MAX_CONTEXT = 50

DEFAULT_TIMEOUT = 10
HARD_MAX_TIMEOUT = 30

SEP_HEAVY = "═" * 59
SEP_LIGHT = "─" * 59

VERSION_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}")


# ----------------------------------------------------------
# Exit codes
# ----------------------------------------------------------

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_ENVIRONMENT = 2
EXIT_TIMEOUT = 3


# ----------------------------------------------------------
# Immutable data structures
# ----------------------------------------------------------

@dataclass(frozen=True)
class Backend:
    name: str
    executable: str


@dataclass(frozen=True)
class Match:
    version: str
    file: str
    line_number: int
    line: str
    before: tuple[tuple[int, str], ...] = ()
    after: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True)
class SearchResult:
    matches: tuple[Match, ...]
    versions_count: int
    shown_count: int
    total_count: int
    truncated: bool
    duration_s: float
    timed_out: bool = False


# ----------------------------------------------------------
# Typed errors
# ----------------------------------------------------------

class UsageError(Exception):
    """User error (incompatible flags, invalid value). Exit code 1."""


class EnvironmentSetupError(Exception):
    """Environment error (versions/ absent, backend unavailable). Exit code 2."""


# ----------------------------------------------------------
# Utilities
# ----------------------------------------------------------

def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def clamp(value: int | None, *, default: int, hard_max: int, minimum: int = 0) -> int:
    if value is None:
        return default
    if value < minimum:
        return minimum
    if value > hard_max:
        return hard_max
    return value


COLOR_ENABLED: bool = sys.stdout.isatty()

DEBUG: bool = os.environ.get("HA_SEARCH_DEBUG", "").lower() in ("1", "true")


def c(text: str, code: str) -> str:
    if not COLOR_ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


# ----------------------------------------------------------
# Backend selection
# ----------------------------------------------------------

def select_backend() -> Backend:
    for candidate in RG_CANDIDATES:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            return Backend(name="rg", executable=resolved)

    for candidate in GREP_CANDIDATES:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and Path(resolved).exists():
            eprint("[ha-archive-search] warning: ripgrep unavailable, grep fallback activated")
            return Backend(name="grep", executable=resolved)

    raise EnvironmentSetupError("no backend available: neither ripgrep (rg) nor grep found")


# ----------------------------------------------------------
# Version resolution
# ----------------------------------------------------------

def list_version_dirs() -> list[Path]:
    if not VERSIONS_ROOT.exists():
        raise EnvironmentSetupError(f"versions/ not found: {VERSIONS_ROOT}")
    if not VERSIONS_ROOT.is_dir():
        raise EnvironmentSetupError(f"versions/ is not a directory: {VERSIONS_ROOT}")

    raw = [p for p in VERSIONS_ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")]

    conforming: list[Path] = []
    non_conforming: list[Path] = []
    for p in raw:
        if VERSION_NAME_RE.match(p.name):
            conforming.append(p)
        else:
            non_conforming.append(p)

    for nc in non_conforming:
        eprint(
            f"[ha-archive-search] warning: directory does not match ISO prefix, ignored: {nc.name}"
        )

    conforming.sort(key=lambda p: p.name)

    if not conforming:
        raise EnvironmentSetupError(f"no version available in {VERSIONS_ROOT}")

    return conforming


def summarize_available_versions(versions: list[Path], limit: int = 10) -> str:
    names = [v.name for v in versions]
    shown = names[:limit]
    lines = "\n".join(f"  - {name}" for name in shown)
    remaining = len(names) - len(shown)
    if remaining > 0:
        lines += f"\n  - and {remaining} more"
    return lines


def resolve_versions(args: argparse.Namespace) -> list[Path]:
    versions = list_version_dirs()

    selector_count = sum([bool(args.latest), bool(args.version), bool(args.all_versions)])

    if selector_count > 1:
        raise UsageError("--latest, --version and --all-versions are mutually exclusive")

    if selector_count == 0 or args.latest:
        return [versions[-1]]

    if args.all_versions:
        return list(versions)

    prefix = args.version
    matches = [v for v in versions if v.name.startswith(prefix)]

    if len(matches) == 1:
        return matches

    if not matches:
        available = summarize_available_versions(versions)
        raise UsageError(
            f"no version matches prefix: {prefix}\n"
            f"Available versions:\n{available}"
        )

    listed = "\n".join(f"  - {m.name}" for m in matches[:20])
    remaining = len(matches) - min(len(matches), 20)
    if remaining > 0:
        listed += f"\n  - and {remaining} more"
    raise UsageError(
        f"ambiguous version prefix: {prefix}\n"
        f"Matching versions:\n{listed}"
    )


# ----------------------------------------------------------
# Perimeter guard
# ----------------------------------------------------------

def enforce_perimeter(paths: list[Path]) -> list[Path]:
    """Verify that each resolved path (realpath) belongs to VERSIONS_ROOT.

    Technical guard for the *bounded perimeter* invariant.
    Raises PermissionError on any out-of-bounds path. No silent fallback.
    """
    root_real = Path(os.path.realpath(VERSIONS_ROOT))

    checked: list[Path] = []
    for path in paths:
        real = Path(os.path.realpath(path))
        try:
            real.relative_to(root_real)
        except ValueError:
            raise PermissionError(f"path outside versions/ perimeter: {path}")
        checked.append(real)
    return checked


# ----------------------------------------------------------
# CLI parsing
# ----------------------------------------------------------

class _ArgParser(argparse.ArgumentParser):
    """argparse exits with code 2 by default. The contract requires code 1 on usage errors."""

    def error(self, message: str) -> None:
        eprint(f"[ha-archive-search] usage error: {message}")
        raise SystemExit(EXIT_USAGE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _ArgParser(
        description="ha-archive-search — bounded search engine for archived Home Assistant versions."
    )

    parser.add_argument("--query", required=True, help="Text or regex to search.")

    g_versions = parser.add_argument_group("Version selection")
    g_versions.add_argument("--latest", action="store_true", help="Search in the latest version.")
    g_versions.add_argument("--version", help="Unambiguous version prefix.")
    g_versions.add_argument("--all-versions", action="store_true", help="Search in all versions.")

    g_docs = parser.add_argument_group("Documentation scope")
    g_docs.add_argument("--exclude-docs", action="store_true", help=f"Exclude {DOCS_DIR}/ directory.")
    g_docs.add_argument("--docs-only", action="store_true", help=f"Search only in {DOCS_DIR}/ directory.")

    g_search = parser.add_argument_group("Search")
    g_search.add_argument("--case-sensitive", action="store_true", help="Case-sensitive search.")
    g_search.add_argument("--regex", action="store_true", help="Interpret query as regex.")

    g_output = parser.add_argument_group("Output")
    g_output.add_argument("--mode", choices=["compact", "context"], default="compact")
    g_output.add_argument("--context", type=int, default=DEFAULT_CONTEXT)
    g_output.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    g_output.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)

    args = parser.parse_args(argv)

    if args.exclude_docs and args.docs_only:
        parser.error("--exclude-docs and --docs-only are mutually exclusive")

    args.context = clamp(args.context, default=DEFAULT_CONTEXT, hard_max=HARD_MAX_CONTEXT, minimum=0)
    args.max_results = clamp(args.max_results, default=DEFAULT_MAX_RESULTS, hard_max=HARD_MAX_RESULTS, minimum=1)
    args.timeout = clamp(args.timeout, default=DEFAULT_TIMEOUT, hard_max=HARD_MAX_TIMEOUT, minimum=1)

    args.query = args.query.strip()
    if not args.query:
        parser.error("--query cannot be empty")

    return args


# ----------------------------------------------------------
# Python-level filtering (defense in depth)
# ----------------------------------------------------------

def is_excluded_rel(rel: str) -> bool:
    parts = rel.split("/")
    return any(part in EXCLUDED_DIRS for part in parts)


def is_allowed_extension(rel: str) -> bool:
    suffix = Path(rel).suffix.lower()
    return suffix in EXTENSIONS


# ----------------------------------------------------------
# Backend command builders
# ----------------------------------------------------------

def build_rg_cmd(backend: Backend, args: argparse.Namespace, root: Path) -> list[str]:
    """Build the rg command that enumerates `root`.

    Extension and directory filtering is delegated to rg via --glob.
    Field separator is forced to \\0 via --null for unambiguous parsing
    of paths containing ':' or '-'.

    Argument order discipline:
        rg [flags...] [filters...] --regexp <pattern> <root>
    """
    cmd: list[str] = [
        backend.executable,
        "--line-number",
        "--with-filename",
        "--color", "never",
        "--null",
        "--no-messages",
        "--no-follow",
    ]

    for ext in EXTENSIONS:
        cmd.extend(["--glob", f"*{ext}"])

    for d in EXCLUDED_DIRS:
        cmd.extend(["--glob", f"!**/{d}/**"])

    if args.exclude_docs:
        cmd.extend(["--glob", f"!**/{DOCS_DIR}/**"])

    if not args.case_sensitive:
        cmd.append("--ignore-case")

    if not args.regex:
        cmd.append("--fixed-strings")

    if args.mode == "context" and args.context > 0:
        cmd.extend(["--context", str(args.context)])

    cmd.extend(["--regexp", args.query])

    if args.docs_only:
        cmd.append(str(root / DOCS_DIR))
    else:
        cmd.append(str(root))

    return cmd


def build_grep_cmd(backend: Backend, args: argparse.Namespace, root: Path) -> list[str]:
    """Build the recursive grep command.

    -Z forces \\0 separator between path and rest, enabling unambiguous
    parsing of paths containing ':' or '-'.

    Argument order discipline (canonical GNU):
        grep [flags...] [filters...] -e <pattern> <root>
    """
    cmd: list[str] = [
        backend.executable,
        "-r",
        "-n",
        "-H",
        "-I",
        "-Z",
        "-s",
    ]

    for ext in EXTENSIONS:
        cmd.append(f"--include=*{ext}")

    for d in EXCLUDED_DIRS:
        cmd.append(f"--exclude-dir={d}")

    if args.exclude_docs:
        cmd.append(f"--exclude-dir={DOCS_DIR}")

    if not args.case_sensitive:
        cmd.append("-i")

    if args.regex:
        cmd.append("-E")
    else:
        cmd.append("-F")

    if args.mode == "context" and args.context > 0:
        cmd.extend(["-C", str(args.context)])

    cmd.extend(["-e", args.query])

    if args.docs_only:
        cmd.append(str(root / DOCS_DIR))
    else:
        cmd.append(str(root))

    return cmd


# ----------------------------------------------------------
# Backend output parsing (\\0 separator)
# ----------------------------------------------------------

def split_record(line: str) -> tuple[str, str, str] | None:
    """Split a backend output line formatted with \\0.

    Expected format: <path>\\0<line_number><sep><content>
    where <sep> is ':' for a match and '-' for a context line.

    Returns (path, sep, rest) or None if the line does not match
    (e.g. '--' group separator lines in context mode).
    """
    if not line or "\0" not in line:
        return None

    path_part, _, rest = line.partition("\0")
    if not rest:
        return None

    idx = 0
    while idx < len(rest) and rest[idx].isdigit():
        idx += 1
    if idx == 0 or idx >= len(rest):
        return None

    sep = rest[idx]
    if sep not in (":", "-"):
        return None

    line_no_str = rest[:idx]
    content = rest[idx + 1:]

    return path_part, sep, f"{line_no_str}{sep}{content}"


def parse_record(
    raw: str, version_dir: Path, root_real: Path
) -> tuple[str, int, str, str] | None:
    """Return (rel, line_number, sep, content) or None.

    Verifies the path belongs to the perimeter (defense in depth).
    """
    rec = split_record(raw)
    if rec is None:
        return None
    path_part, _, rest = rec

    idx = 0
    while idx < len(rest) and rest[idx].isdigit():
        idx += 1
    if idx == 0 or idx >= len(rest):
        return None
    sep = rest[idx]
    line_no = int(rest[:idx])
    content = rest[idx + 1:]

    try:
        real = Path(os.path.realpath(path_part))
        real.relative_to(root_real)
    except (ValueError, OSError):
        return None

    try:
        rel = real.relative_to(Path(os.path.realpath(version_dir))).as_posix()
    except ValueError:
        return None

    if not is_allowed_extension(rel):
        return None
    if is_excluded_rel(rel):
        return None

    return rel, line_no, sep, content


def parse_compact_output(
    output: str, *, version: str, version_dir: Path, root_real: Path
) -> list[Match]:
    matches: list[Match] = []
    for raw in output.splitlines():
        if raw == "--":
            continue
        parsed = parse_record(raw, version_dir, root_real)
        if parsed is None:
            continue
        rel, line_no, sep, content = parsed
        if sep != ":":
            continue
        matches.append(Match(version=version, file=rel, line_number=line_no, line=content))
    return matches


def parse_context_output(
    output: str, *, version: str, version_dir: Path, root_real: Path
) -> list[Match]:
    """Parse context mode output.

    Each rg/grep group is delimited by '--'. Within a group, match lines
    (sep ':') and context lines (sep '-') follow each other.
    A match line opens a new Match; context lines are assigned to it
    based on their relative position.
    """
    matches: list[Match] = []
    current_match_line: int | None = None
    current_match_content: str | None = None
    current_file: str | None = None
    before: list[tuple[int, str]] = []
    after: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal current_match_line, current_match_content, current_file, before, after
        if current_match_line is not None and current_file is not None:
            matches.append(
                Match(
                    version=version,
                    file=current_file,
                    line_number=current_match_line,
                    line=current_match_content or "",
                    before=tuple(sorted(before, key=lambda x: x[0])),
                    after=tuple(sorted(after, key=lambda x: x[0])),
                )
            )
        current_match_line = None
        current_match_content = None
        current_file = None
        before = []
        after = []

    for raw in output.splitlines():
        if raw == "--":
            flush()
            continue

        parsed = parse_record(raw, version_dir, root_real)
        if parsed is None:
            continue
        rel, line_no, sep, content = parsed

        if sep == ":":
            if current_match_line is not None:
                flush()
            current_match_line = line_no
            current_match_content = content
            current_file = rel
        else:
            if current_match_line is None:
                if current_file is None:
                    current_file = rel
                if current_file == rel:
                    before.append((line_no, content))
            else:
                if current_file == rel:
                    if line_no < current_match_line:
                        before.append((line_no, content))
                    elif line_no > current_match_line:
                        after.append((line_no, content))

    flush()
    return matches


# ----------------------------------------------------------
# Backend execution (UNIQUE subprocess boundary)
# ----------------------------------------------------------

def run_search(
    *, backend: Backend, versions: list[Path], args: argparse.Namespace
) -> SearchResult:
    started = time.monotonic()

    root_real = Path(os.path.realpath(VERSIONS_ROOT))

    all_matches: list[Match] = []
    truncated = False

    for version_dir in versions:
        version_name = version_dir.name

        if args.docs_only and not (version_dir / DOCS_DIR).is_dir():
            eprint(
                f"[ha-archive-search] warning: {DOCS_DIR}/ not found in {version_name}, skipping"
            )
            continue

        if backend.name == "rg":
            cmd = build_rg_cmd(backend, args, version_dir)
        else:
            cmd = build_grep_cmd(backend, args, version_dir)

        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - started
            shown = all_matches[: args.max_results]
            return SearchResult(
                matches=tuple(shown),
                versions_count=len(versions),
                shown_count=len(shown),
                total_count=len(all_matches),
                truncated=True,
                duration_s=duration,
                timed_out=True,
            )

        if proc.returncode not in (0, 1):
            raise EnvironmentSetupError(
                f"backend {backend.name} error on {version_name} "
                f"(exit {proc.returncode}): {proc.stderr.strip()}"
            )

        if args.mode == "compact":
            version_matches = parse_compact_output(
                proc.stdout, version=version_name, version_dir=version_dir, root_real=root_real
            )
        else:
            version_matches = parse_context_output(
                proc.stdout, version=version_name, version_dir=version_dir, root_real=root_real
            )

        all_matches.extend(version_matches)

        if len(all_matches) > args.max_results:
            truncated = True
            break

    duration = time.monotonic() - started
    shown = all_matches[: args.max_results]

    return SearchResult(
        matches=tuple(shown),
        versions_count=len(versions),
        shown_count=len(shown),
        total_count=len(all_matches),
        truncated=truncated,
        duration_s=duration,
    )


# ----------------------------------------------------------
# Output formatting
# ----------------------------------------------------------

def format_compact(result: SearchResult) -> list[str]:
    lines: list[str] = []
    for m in result.matches:
        version = c(f"[{m.version}]", "32")
        line_no = c(str(m.line_number), "36")
        lines.append(f"{version} {m.file}:{line_no}: {m.line}")
    return lines


def format_context(result: SearchResult) -> list[str]:
    lines: list[str] = []

    for m in result.matches:
        lines.append(c(SEP_HEAVY, "90"))
        lines.append(
            f"{c(f'[{m.version}]', '32')} {m.file}:{c(str(m.line_number), '36')}"
        )
        lines.append(c(SEP_LIGHT, "90"))

        for line_no, line in m.before:
            lines.append(f"  {line_no:4d}  {line}")

        lines.append(f"> {m.line_number:4d}  {m.line}")

        for line_no, line in m.after:
            lines.append(f"  {line_no:4d}  {line}")

    if result.matches:
        lines.append(c(SEP_HEAVY, "90"))

    return lines


def format_footer(result: SearchResult) -> str:
    plural_res = "result" if result.shown_count <= 1 else "results"
    plural_versions = "version" if result.versions_count <= 1 else "versions"

    if result.timed_out:
        return (
            f"{SEP_LIGHT}\n"
            f"query timeout: {result.shown_count} partial {plural_res} (not guaranteed) "
            f"across {result.versions_count} {plural_versions}  •  duration {result.duration_s:.2f} s"
        )

    if result.truncated:
        return (
            f"{SEP_LIGHT}\n"
            f"results truncated: {result.shown_count} displayed out of at least {result.total_count}"
            f"  •  duration {result.duration_s:.2f} s"
        )

    return (
        f"{SEP_LIGHT}\n"
        f"{result.shown_count} {plural_res} across {result.versions_count} {plural_versions}"
        f"  •  duration {result.duration_s:.2f} s"
    )


def print_output(result: SearchResult, args: argparse.Namespace) -> None:
    lines = format_compact(result) if args.mode == "compact" else format_context(result)
    for line in lines:
        print(line)
    print(format_footer(result))


# ----------------------------------------------------------
# Orchestration
# ----------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else EXIT_USAGE

    try:
        backend = select_backend()
        versions = resolve_versions(args)
        enforce_perimeter(versions)

        result = run_search(backend=backend, versions=versions, args=args)
        print_output(result, args)

        if result.timed_out:
            return EXIT_TIMEOUT
        return EXIT_OK

    except UsageError as exc:
        eprint(f"[ha-archive-search] usage error: {exc}")
        return EXIT_USAGE
    except EnvironmentSetupError as exc:
        eprint(f"[ha-archive-search] environment error: {exc}")
        return EXIT_ENVIRONMENT
    except PermissionError as exc:
        eprint(f"[ha-archive-search] perimeter error: {exc}")
        return EXIT_ENVIRONMENT
    except subprocess.TimeoutExpired as exc:
        eprint(f"[ha-archive-search] query timeout: {exc}")
        return EXIT_TIMEOUT
    except Exception as exc:
        eprint(f"[ha-archive-search] error: {exc}")
        if DEBUG:
            raise
        return EXIT_ENVIRONMENT


if __name__ == "__main__":
    raise SystemExit(main())