# ha-archive-search — Plan de release v0.2.0

## Objectif

Remplacer le rendu stdout brut (`<pre>` monobloc) par un renderer HTML structuré, hiérarchique et lisible sur mobile. Aucune modification du moteur CLI. Aucune dépendance ajoutée.

---

## Périmètre

| Fichier | Statut |
|---|---|
| `src/ha_archive_search/engine.py` | **Inchangé** |
| `src/ha_archive_search/webapp.py` | **Modifié** |
| `src/ha_archive_search/templates/index.html` | **Modifié** |
| `src/ha_archive_search/__init__.py` | **Modifié** (version bump) |
| `pyproject.toml` | **Modifié** (version bump) |
| `CHANGELOG.md` | **Modifié** (entrée v0.2.0) |
| `docker/Dockerfile` | **Inchangé** |
| `docker/docker-compose.yml` | **Inchangé** |

---

## 1. `webapp.py` — ajouts

### 1.1 Constantes regex

Ajouter après les imports existants, avant la définition de `app` :

```python
COMPACT_LINE_RE = re.compile(
    r"^\[(?P<version>[^\]]+)\]\s+"
    r"(?P<path>.*?):"
    r"(?P<line>\d+):"
    r"(?P<content>.*)$"
)

SUMMARY_RE = re.compile(
    r"(?P<count>\d+)\s+results?\s+across\s+(?P<versions>\d+)\s+versions?\s+•\s+duration\s+(?P<duration>[0-9.,]+)\s+s"
)
```

**Note sur `SUMMARY_RE`** : le moteur CLI v0.1.0 produit son footer en anglais (`results across N versions • duration X s`). Le regex ci-dessus correspond à ce format exact. Ne pas utiliser la version française d'Arsenal Search.

**Contrat implicite** : à partir de v0.2.0, le wording du footer compact du moteur devient un contrat de renderer. Toute modification future du wording dans `engine.py` (libellés, ponctuation, symbole `•`) doit soit préserver la compatibilité avec `SUMMARY_RE`, soit mettre à jour le parser en même temps. Un "small wording cleanup" dans le moteur casse silencieusement les badges summary sans erreur visible — le renderer bascule sur fallback sans avertissement.

### 1.2 Fonction `parse_compact_output()`

Ajouter avant la fonction `empty_template()` :

```python
def parse_compact_output(output: str) -> tuple[dict | None, dict | None]:
    """Parse le stdout compact du moteur en structure hiérarchique.

    Retourne (grouped, summary) où :
      - grouped = {version: {path: [{"line": str, "content": str}, ...]}}
      - summary = {"count": str, "versions": str, "duration": str} ou None

    Retourne (None, summary) si aucun match parsé (résultat vide ou mode contexte).
    """
    grouped = {}
    summary = None
    parsed_count = 0

    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")

        m_summary = SUMMARY_RE.fullmatch(line)
        if m_summary:
            summary = {
                "count": m_summary.group("count"),
                "versions": m_summary.group("versions"),
                "duration": m_summary.group("duration").replace(",", "."),
            }
            continue

        if not line or line.startswith("─") or line.startswith("═"):
            continue

        m = COMPACT_LINE_RE.match(line)
        if not m:
            continue

        version = m.group("version")
        path = m.group("path")
        line_no = m.group("line")
        content = m.group("content").rstrip()

        grouped.setdefault(version, {}).setdefault(path, []).append(
            {"line": line_no, "content": content}
        )
        parsed_count += 1

    if parsed_count == 0:
        return None, summary

    return grouped, summary
```

**Note sur `fullmatch` vs `search`** : `SUMMARY_RE.fullmatch(line)` est utilisé à la place de `search()` car le footer est une ligne complète, pas un fragment. `search()` introduirait un risque de faux positif si une ligne de contenu contient accidentellement le même pattern. `fullmatch()` ancre le match sur la ligne entière.

**Invariant d'ordre** : `grouped` est un `dict` Python standard. En Python 3.7+, l'ordre d'insertion est garanti. Le renderer affiche donc les versions, fichiers et hits dans l'ordre exact du stdout moteur. Aucun tri supplémentaire n'est appliqué côté webapp. Tout changement d'ordre de tri dans le moteur se répercute directement dans le renderer — c'est intentionnel.

### 1.3 Modification de `empty_template()`

Ajouter `parsed` et `summary` aux defaults :

```python
def empty_template(**kwargs):
    defaults = {
        "app_name": APP_NAME,
        "query": "",
        "output": "",
        "error": "",
        "parsed": None,       # AJOUT
        "summary": None,      # AJOUT
        "context": False,
        "latest": False,
        "all_versions": False,
        "exclude_docs": False,
        "docs_only": False,
    }
    defaults.update(kwargs)
    return render_template("index.html", **defaults)
```

### 1.4 Modification de la route `POST /search`

Remplacer le bloc final de la route `search()` :

**Avant :**
```python
    output = result.stdout.strip() or "No results."

    return empty_template(
        query=query,
        output=output,
        error="",
        **options,
    )
```

**Après :**
```python
    output = result.stdout.strip() or "No results."

    parsed = None
    summary = None
    if not options.get("context"):
        parsed, summary = parse_compact_output(output)

    return empty_template(
        query=query,
        output=output,
        error="",
        parsed=parsed,
        summary=summary,
        **options,
    )
```

**Invariant** : le mode contexte (`--mode context`) produit un stdout multi-lignes non parsable par `COMPACT_LINE_RE`. Dans ce cas, `parsed` reste `None` et le template bascule sur le fallback `<pre>` existant. Comportement identique à v0.1.0 pour ce mode.

### 1.5 Import `re` — vérification

`re` est déjà importé en v0.1.0. Aucun ajout d'import requis.

---

## 2. `templates/index.html` — modifications CSS et template

### 2.1 Variables CSS — ajout dans `:root`

Ajouter dans le bloc `:root` existant :

```css
--hit-bg: #fff7ed;
--hit-border: #fed7aa;
```

### 2.2 Nouvelles règles CSS

Ajouter avant `@media (max-width: 700px)` :

```css
.summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.badge {
  display: inline-flex;
  padding: 5px 9px;
  border-radius: 999px;
  background: #eef2ff;
  color: #3730a3;
  font-size: 12px;
  font-weight: 700;
}

.version-block {
  margin-top: 18px;
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  background: #fff;
}

.version-title {
  padding: 12px 14px;
  background: #f1f5f9;
  border-bottom: 1px solid var(--border);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  font-weight: 800;
  overflow-wrap: anywhere;
}

details.file-block {
  border-bottom: 1px solid var(--border);
}

details.file-block:last-child {
  border-bottom: 0;
}

details.file-block summary {
  cursor: pointer;
  padding: 12px 14px;
  list-style: none;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
}

details.file-block summary::-webkit-details-marker {
  display: none;
}

.file-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.file-count {
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 12px;
}

.hits {
  padding: 0 14px 14px;
  display: grid;
  gap: 8px;
}

.hit {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 10px;
  align-items: start;
  border: 1px solid var(--hit-border);
  background: var(--hit-bg);
  border-radius: 10px;
  padding: 9px 10px;
}

.line-no {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  color: #9a3412;
  font-weight: 800;
  font-size: 12px;
  padding-top: 2px;
}

.line-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 1.45;
}
```

### 2.3 Media query mobile — ajout

Dans le bloc `@media (max-width: 700px)` existant, ajouter :

```css
.hit { grid-template-columns: 52px 1fr; }
details.file-block summary { display: block; }
.file-count { display: block; margin-top: 5px; }
```

### 2.4 Bloc résultats — remplacement

**Avant** (bloc entier à remplacer) :
```html
{% if output %}
  <section class="result-panel block">
    <pre class="raw">{{ output }}</pre>
  </section>
{% elif error %}
  <section class="result-panel block">
    <pre class="error">{{ error }}</pre>
  </section>
{% endif %}
```

**Après :**
```html
{% if parsed %}
  <section class="result-panel block">
    {% if summary %}
      <div class="summary">
        <span class="badge">{{ summary.count }} results</span>
        <span class="badge">{{ summary.versions }} version{% if summary.versions != "1" %}s{% endif %}</span>
        <span class="badge">{{ summary.duration }} s</span>
      </div>
    {% endif %}

    {% for version, files in parsed.items() %}
      <div class="version-block">
        <div class="version-title">{{ version }}</div>

        {% for path, hits in files.items() %}
          <details class="file-block" open>
            <summary>
              <span class="file-path">{{ path }}</span>
              <span class="file-count">{{ hits|length }} occurrence{% if hits|length > 1 %}s{% endif %}</span>
            </summary>

            <div class="hits">
              {% for hit in hits %}
                <div class="hit">
                  <div class="line-no">L{{ hit.line }}</div>
                  <pre class="line-content">{{ hit.content }}</pre>
                </div>
              {% endfor %}
            </div>
          </details>
        {% endfor %}
      </div>
    {% endfor %}
  </section>
{% elif output %}
  <section class="result-panel block">
    <pre class="raw">{{ output }}</pre>
  </section>
{% elif error %}
  <section class="result-panel block">
    <pre class="error">{{ error }}</pre>
  </section>
{% endif %}
```

**Invariant de fallback** : `{% elif output %}` préserve le rendu `<pre>` pour le mode contexte brut et pour tout stdout non parsable. La régression est impossible.

---

## 3. Version bump

### 3.1 `pyproject.toml`

```toml
version = "0.2.0"
```

### 3.2 `src/ha_archive_search/__init__.py`

Mettre à jour `__version__` :

```python
__version__ = "0.2.0"
```

---

## 4. `CHANGELOG.md` — entrée v0.2.0

Ajouter en tête du fichier, avant l'entrée `[0.1.0]` :

```markdown
## [0.2.0] — 2026-XX-XX

### Added

#### Webapp

- `webapp.py`: `parse_compact_output()` — structured parser for compact engine stdout.
  - Parses each match line via `COMPACT_LINE_RE` into a `{version → {path → [hits]}}` hierarchy.
  - Parses footer line via `SUMMARY_RE` into `{count, versions, duration}` summary dict.
  - Returns `(None, summary)` on empty result set; webapp falls back to raw `<pre>` block.
  - Context mode (`--mode context`) bypasses parser; raw fallback applies.
- `webapp.py`: `COMPACT_LINE_RE`, `SUMMARY_RE` — compiled regex constants for stdout parsing.
- `webapp.py`: `parsed` and `summary` passed to template on every search response.
- `templates/index.html`: structured result renderer.
  - KPI badge row: result count, version count, duration.
  - Per-version block with monospace header.
  - Per-file collapsible `<details>` block with occurrence count.
  - Per-match hit row: line number + content, no horizontal scroll.
  - Mobile-first layout: adaptive grid, block summary on narrow viewport.
  - Raw `<pre>` fallback preserved for context mode and unparsable output.

### Changed

- Result rendering: compact mode now produces structured HTML instead of raw stdout dump.
- No engine changes. No new dependencies.
```

---

## 5. Renderer doctrine

Le renderer est une couche de présentation pure. Il ne modifie pas, ne normalise pas et n'enrichit pas sémantiquement les données du moteur.

Invariants :

- La source de vérité reste le stdout du moteur CLI. Le renderer ne fait que le mettre en forme.
- `parse_compact_output()` ne corrige pas, ne filtre pas et ne réordonne pas les données. Ce qu'elle reçoit, elle l'affiche.
- Aucun cache de résultat n'est introduit en v0.2.0. `parsed` et `summary` sont des variables locales à la requête HTTP, sans état persistant.
- Le renderer ne doit jamais devenir un moteur caché. Toute logique de sélection, de filtrage ou de classement appartient au moteur CLI.
- Le renderer est best-effort. En cas d'ambiguïté de parsing ou de dérive future du format moteur, le fallback `<pre>` reste la référence authoritative. Un renderer silencieusement dégradé vaut mieux qu'un renderer qui invente des données.

---

## 6. Vérification avant release

Checklist séquentielle :

- [ ] `COMPACT_LINE_RE` — tester sur une ligne de sortie réelle du moteur : `[2026-05-16_16-18_Automatic_backup_2026.5.1_bf7d03c1] 01_customize/divers.yaml:63: binary_sensor.presence_famille_unifiee:`
- [ ] `SUMMARY_RE` — tester sur le footer réel : `131 results across 1 version • duration 0.99 s`
- [ ] Mode compact, résultats non vides → renderer structuré affiché
- [ ] Mode compact, aucun résultat → `<pre>` fallback affiché avec "No results."
- [ ] Mode contexte → `<pre>` fallback affiché (parsed = None)
- [ ] Erreur moteur → bloc erreur affiché
- [ ] Mobile (viewport < 700px) → pas de scroll horizontal, hit grid à 52px
- [ ] `GET /health` → `{"status": "ok", ...}` inchangé
- [ ] `POST /export` → Markdown téléchargé, contenu inchangé (stdout brut, pas le HTML)

---

## 7. Ce qui n'est pas dans cette release

Les points suivants sont explicitement hors périmètre v0.2.0 :

- `--json` flag sur le CLI — non requis, le parser regex sur stdout suffit
- appel Python direct à `run_search()` depuis la webapp — non requis pour ce saut qualitatif
- mode contexte structuré — nécessite un parser dédié, périmètre v0.3.0
- intelligence historique (first seen / last seen / présence N versions) — périmètre v0.4.0
- framework frontend (React, Vue) — hors doctrine
