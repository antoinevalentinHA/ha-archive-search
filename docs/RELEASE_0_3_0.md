## État d'avancement

| Phase | Périmètre | Statut |
|---|---|---|
| **A** | Modèle typé `ParsedResults`, refonte `parse_compact_output()`, adaptation `/search` et `templates/index.html`. Aucun changement visible. | **Intégrée** — commit `72cdcad`. Validée par harnais de non-régression sandbox (6 fixtures, 9 tests modèle) puis smoke test sur l'instance NAS (`/search` compact + contexte, `/export` v0.2.x byte-équivalent hors timestamp). |
| **B** | Refonte `build_markdown_export()` : helpers `render_markdown_query/summary/results`, généralisation `markdown_inline_code()` pour runs de backticks arbitraires, consommation du modèle typé. | À faire. Aucune touche prévue à `index.html` ni à `engine.py`. |
| **C** | Bump version `0.3.0`, re-export des dataclasses dans `__init__.py` avec marqueur `Internal model — no backward compatibility guarantee before v1.0`, amendement `docs/contrat_webapp.md`, mise à jour `README.md`, consolidation de l'entrée CHANGELOG `[Unreleased]` en `[0.3.0]`. | À faire. |

**Notes** :

- Tant que la Phase C n'est pas livrée, le package reste estampillé `0.2.1`. Le contrat webapp v1 reste en vigueur tel quel : `/export` se comporte toujours en v0.2.x, l'amendement n'est pas encore actif.
- L'entrée CHANGELOG `[Unreleased]` documente la Phase A comme socle interne déjà intégré. Elle sera fusionnée dans l'entrée `[0.3.0]` finale au moment du bump.
- Le présent document reste la spec de référence. Les sections §1 à §15 sont **non amendées** par cette note d'état : elles décrivent la cible v0.3.0 complète, pas l'incrément Phase A.

---

# ha-archive-search — Plan de release v0.3.0

## Objectif

Remplacer l'export Markdown brut (enveloppe minimale autour du stdout CLI) par un export Markdown **structuré, déterministe et lisible**, destiné au partage humain et à l'analyse par LLM. Aucune modification du moteur CLI. Aucune nouvelle dépendance.

Cette release est une **rupture contrôlée du contrat webapp v1** : l'invariant "l'export ne réinterprète pas le stdout du moteur" est explicitement amendé pour la couche `/export`. L'invariant reste intact côté `/search` (déjà restructuré en v0.2.0) et côté moteur CLI (qui ne change pas).

---

## Périmètre

| Fichier | Statut |
|---|---|
| `src/ha_archive_search/engine.py` | **Inchangé** |
| `src/ha_archive_search/webapp.py` | **Modifié** (modèle interne typé, refonte `build_markdown_export`, helpers Markdown) |
| `src/ha_archive_search/templates/index.html` | **Modifié** (adaptation au modèle typé `ParsedResults`) |
| `src/ha_archive_search/__init__.py` | **Modifié** (version bump, export dataclasses) |
| `pyproject.toml` | **Modifié** (version bump) |
| `CHANGELOG.md` | **Modifié** (entrée v0.3.0) |
| `README.md` | **Modifié** (section export Markdown) |
| `docs/contrat_webapp.md` | **Modifié** (amendement section `/export`, non-goals, versionnage) |
| `docker/Dockerfile` | **Inchangé** |
| `docker/docker-compose.yml` | **Inchangé** |
| `docker/docker-compose.synology.yml` | **Inchangé** |

---

## 1. Amendement du contrat webapp

### 1.1 Position doctrinale

Le contrat webapp v1 (`docs/contrat_webapp.md`) stipulait :

> The Markdown export defined by the present contract is **unstructured**: it is a minimal envelope around the exact stdout. No semantic structuring (by version, file, or match) is produced.

> Any future evolution toward structured export would require structured engine output (e.g. a `--output-format json` flag, already listed as Phase 2 compatibility in the engine contract) and an explicit amendment.

v0.3.0 lève cette restriction **sans** introduire de flag `--output-format json` côté moteur. Le renderer Markdown structuré consomme le même stdout compact que le renderer HTML v0.2.0, via la même fonction `parse_compact_output()`. Aucune sortie machine n'est ajoutée au moteur CLI.

### 1.2 Principe du nouvel export

`/export` :

1. valide les paramètres du formulaire (règles inchangées) ;
2. invoque `engine.py` via `subprocess.run()` avec les mêmes flags que `/search` (inchangé) ;
3. **parse** le stdout compact via `parse_compact_output()` ;
4. **rend** un Markdown structuré déterministe à partir de la structure parsée ;
5. retourne le fichier au navigateur en pièce jointe (inchangé).

Le mode contexte conserve un fallback `text` brut, identique à v0.2.x côté `/search`.

### 1.3 Invariants préservés

Les invariants structurels du contrat webapp v1 restent en vigueur :

- **Read-only** : aucun fichier écrit sur l'hôte. Le Markdown est généré en mémoire et transmis dans la réponse HTTP.
- **Engine authority** : `/export` utilise exactement les mêmes paramètres et le même mode d'invocation que `/search`. Aucune logique grep n'est dupliquée.
- **Server-side bounds** : les plafonds du moteur (résultats, contexte, durée) s'appliquent intégralement.
- **No free shell** : la requête utilisateur reste passée via `subprocess.run(..., shell=False)`.
- **No persistent state** : pas d'historique d'export, pas de cache.

### 1.4 Invariants amendés

- **Engine authority** (clause export) : *amendée*. L'export `parse` et `restructure` désormais le stdout. Il ne **réinterprète pas sémantiquement** (pas de classement, pas de filtrage, pas de dérivation historique). Le contenu textuel de chaque hit est préservé sans transformation sémantique : la chaîne extraite par `COMPACT_LINE_RE` est insérée telle quelle dans le rendu, sous une encapsulation d'échappement Markdown adaptative (cf. §2.6). Aucune normalisation de casse, de blanc, de ponctuation ou de retour ligne intra-hit.
- **Format export** : non plus "enveloppe minimale autour du stdout", mais "rendu Markdown structuré dérivé sans perte sémantique du stdout compact".

### 1.5 Invariants nouveaux

- **Déterminisme** : pour un même stdout en entrée, le renderer produit un Markdown stable et reproductible, à variations près limitées au timestamp `Export date`. La structure `parsed` étant un agrégat déterministe et l'ordre d'itération étant stable (cf. §1.5 ordre stable), aucune variation fonctionnelle entre deux runs ne doit apparaître. Cette stabilité ne s'étend pas aux détails non-significatifs (séquences exactes de whitespace, ordre interne d'attributs sérialisés, encodage de retours ligne) qui peuvent varier au gré des évolutions de Python, Jinja ou des librairies amont — c'est la stabilité sémantique du rendu qui est garantie, pas l'égalité binaire stricte.
- **Préservation sémantique** : tout hit présent dans le stdout compact est présent dans le Markdown, avec son numéro de ligne et son contenu textuel intacts. Le footer moteur (compteurs, durée, troncature signalée) est préservé via le bloc `## Summary`.
- **Pas d'interprétation sémantique ou historique** : le renderer ne calcule ni first-seen, ni last-seen, ni présence multi-versions, ni diff inter-versions, ni aucune dérivation sémantique. L'agrégation structurelle (groupement par version, par fichier, compteur d'occurrences par fichier) est admise — c'est de la mise en forme, pas de l'inférence. Toute capacité d'inférence appartient au périmètre v0.4.0.
- **Ordre stable** : l'ordre des versions, fichiers et hits dans le Markdown reproduit exactement l'ordre du stdout. Aucun tri supplémentaire n'est appliqué (cf. invariant d'ordre v0.2.0).

### 1.6 Modèle interne typé

Le parser v0.2.0 retournait des `dict` libres. v0.3.0 introduit un **modèle interne typé immuable** entre `parse_compact_output()` et les renderers HTML/Markdown. C'est une condition nécessaire à la doctrine de déterminisme et de stabilité ci-dessus : un contrat de structure dispersé en clés de dict implicites n'est pas un contrat.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Hit:
    line: int          # numéro de ligne dans le fichier source (int, pas str)
    content: str       # contenu textuel brut du hit, non échappé

@dataclass(frozen=True)
class FileResult:
    path: str          # chemin relatif sous <version>/
    hits: tuple[Hit, ...]   # tuple immuable, ordre = ordre stdout

@dataclass(frozen=True)
class VersionResult:
    version: str       # identifiant de version brut (ex: 2026-05-16_..._bf7d03c1)
    files: tuple[FileResult, ...]

@dataclass(frozen=True)
class Summary:
    count: int
    versions: int
    duration: str      # str pour préserver la précision décimale émise par le moteur

@dataclass(frozen=True)
class ParsedResults:
    versions: tuple[VersionResult, ...]   # vide si pas de hits parsés
    summary: Summary | None
```

**Justification des choix de type** :

- `frozen=True` : immutabilité explicite, le renderer ne peut pas muter par inadvertance.
- `tuple` plutôt que `list` : signal d'intention "structure figée à la construction", aligné avec `frozen=True`.
- `line: int` : conversion à la construction. Le `line_no` était `str` en v0.2.0 par paresse de typage. La conversion à `int` est sûre puisque `COMPACT_LINE_RE` capture `\d+`.
- `duration: str` : préservation de la précision exacte émise par le moteur (gestion `.replace(",", ".")` pour les locales). Pas de cast `float` qui introduirait des arrondis.
- `Summary` typée (et non `dict`) : même raison que le reste — couplage parser/renderer explicite.

**Migration template HTML** : le template `index.html` v0.2.0 utilise `parsed.items()` et `files.items()`. La transition vers `ParsedResults` impose une réécriture du template (utilisation de `.versions`, `.files`, `.hits`, `.path`, `.version`, `.line`, `.content`). Ce diff est traité au §4.

**Critère de non-régression** : le rendu HTML produit par le nouveau template sur les `ParsedResults` typés doit présenter **une équivalence visuelle et structurelle** avec le rendu v0.2.0 sur les `dict` libres — mêmes blocs, mêmes textes affichés, même hiérarchie, même CSS appliquée. Les différences non-significatives au niveau du DOM brut (ordre attributaire, whitespace inter-balises, comportements internes de Jinja) ne constituent pas une régression. C'est le test 11.13.

---

## 2. Format Markdown cible

### 2.1 Anatomie globale

```markdown
# ha-archive-search — Results

## Query

- Term: `<query>`
- Mode: `compact` | `context`
- Latest only: `yes` | `no`
- All versions: `yes` | `no`
- Documentation: `included` | `excluded` | `only`
- Export date: `YYYY-MM-DD HH:MM`

## Summary

- Results: `<count>`
- Versions: `<versions>`
- Duration: `<duration> s`

## Results

### `<version-1>`

#### `<path-A>` — N occurrence(s)

- **L<line>** — `<content>`
- **L<line>** — `<content>`

#### `<path-B>` — N occurrence(s)

- **L<line>** — `<content>`

### `<version-2>`

#### `<path-C>` — N occurrence(s)

- **L<line>** — `<content>`

---

Export generated by ha-archive-search v0.3.0
```

### 2.2 Bloc `Summary`

- Présent **systématiquement**.
- Si le footer moteur a été parsé : trois items `Results` / `Versions` / `Duration` avec valeurs typées.
- Si le footer n'a pas été parsé (drift moteur, sortie tronquée, mode contexte sans footer reconnaissable) : un unique item `- Summary parsing: ` `` `failed` ``. C'est un signal de diagnostic explicite, pas une dégradation silencieuse.
- Ce choix est révisé par rapport au draft v0.3.0 initial (qui omettait silencieusement le bloc). Justification : v0.2.0 a déjà créé une dépendance critique au wording footer via `SUMMARY_RE` ; v0.3.0 ajoute un deuxième consommateur. Le silence devient inacceptable parce qu'il devient symétrique sur les deux renderers.

### 2.3 Bloc `Results`

- Présent si et seulement si `parsed.versions` est non vide (au moins un hit parsé). Sinon, le bloc `## Results` rend soit `_No results._` (cf. §2.4), soit un fence brut (cf. §2.5).
- Hiérarchie fixe : `### version` → `#### path — N occurrence(s)` → liste à puces des hits.
- Pluriel anglais : `occurrence` si N=1, `occurrences` sinon. Cohérent avec le renderer HTML v0.2.0.
- Chaque hit est un item de liste : `- **L<line>** — <content>`.
- Le contenu du hit est **échappé Markdown** (cf. 2.5) puis encapsulé en code inline si nécessaire.

### 2.4 Cas "résultats vides"

Si le stdout moteur est `"No results."` (string sentinelle retournée par `/search` quand `result.stdout.strip()` est vide), le Markdown produit :

```markdown
# ha-archive-search — Results

## Query

- Term: `<query>`
- ...

## Summary

- Summary parsing: `failed`

## Results

_No results._

---

Export generated by ha-archive-search v0.3.0
```

**Note** : dans ce cas, le moteur a court-circuité et n'a pas émis son footer habituel. `Summary parsing: failed` est le signal correct. Si en pratique le moteur émet bien `0 results across 0 versions • duration X s` même pour zéro hit, alors le bloc `## Summary` s'affichera nominalement avec des zéros. Cela dépend du comportement effectif de `engine.py` à vérifier pendant les tests (§11.3).

### 2.5 Cas "mode contexte"

Le mode contexte produit un stdout multi-lignes non parsable par `COMPACT_LINE_RE`. Comportement v0.3.0 :

```markdown
# ha-archive-search — Results

## Query

- Term: `<query>`
- Mode: `context`
- ...

## Results

<fence>text
<stdout brut moteur, footer inclus>
<fence>

---

Export generated by ha-archive-search v0.3.0
```

Le bloc `## Summary` est tenté : si le footer moteur est présent et parsable en isolation (même `SUMMARY_RE`), il est inséré ; sinon il est omis. Le bloc `## Results` retombe sur le code fence brut, **identique à l'export v0.2.x** pour ce mode. C'est le fallback contractuel.

**Justification** : structurer le mode contexte impliquerait un parser dédié multi-lignes (signalé périmètre v0.3.0 dans le RELEASE_0_2_0.md). Ce parser n'est pas livré ici : v0.3.0 se concentre sur la structuration de l'export en mode compact. Le mode contexte reste lisible via fence brut.

### 2.6 Échappement Markdown du contenu de hit

Le `content` extrait par `COMPACT_LINE_RE` provient de fichiers YAML/Python/HTML/Markdown archivés. Il peut contenir des caractères qui cassent le rendu Markdown si insérés bruts dans une liste à puces : `` ` ``, `*`, `_`, `[`, `]`, `<`, `>`, `|`, `#`, `\`.

**Règle** : tout contenu de hit est encapsulé en **code inline** avec une fence backtick adaptative.

- Si le contenu ne contient pas de backtick : `` `<content>` ``
- Si le contenu contient un ou plusieurs backticks : `` ``  <content>  `` `` (avec espaces de garde si le contenu commence ou finit par un backtick).

La fonction `markdown_inline_code()` existante (`webapp.py` v0.2.1) implémente déjà ce comportement pour la query. Elle est réutilisée telle quelle pour les contenus de hit.

Pour les contenus contenant des séquences de backticks plus longues qu'un seul (rare mais possible dans du Markdown archivé), `markdown_inline_code()` v0.2.1 est insuffisante : elle utilise un délimiteur double fixe. v0.3.0 généralise cette fonction (cf. 3.2).

### 2.7 Échappement Markdown des paths et versions

Les paths et noms de version sont encapsulés en code inline (même fonction `markdown_inline_code()`) pour neutraliser les underscores, points et chevrons typiques des dumps Home Assistant (`2026-05-16_16-18_Automatic_backup_2026.5.1_bf7d03c1`, `binary_sensor.deshumidificateur_actif`, `<entité>`).

---

## 3. `webapp.py` — modifications

### 3.1 Refactor du modèle interne et mutualisation `parse_compact_output()`

`parse_compact_output()` existe depuis v0.2.0 et retourne `tuple[dict | None, dict | None]`. v0.3.0 modifie sa signature pour retourner un objet `ParsedResults` typé (cf. §1.6).

**Nouvelle signature** :

```python
def parse_compact_output(output: str) -> ParsedResults:
    """Parse le stdout compact du moteur en structure typée immuable.

    Retourne toujours un ParsedResults. Si aucun hit parsé,
    parsed.versions est un tuple vide. Si le footer n'est pas matché,
    parsed.summary est None.
    """
    versions_acc: dict[str, dict[str, list[Hit]]] = {}
    summary: Summary | None = None

    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")

        m_summary = SUMMARY_RE.fullmatch(line)
        if m_summary:
            summary = Summary(
                count=int(m_summary.group("count")),
                versions=int(m_summary.group("versions")),
                duration=m_summary.group("duration").replace(",", "."),
            )
            continue

        if not line or line.startswith("─") or line.startswith("═"):
            continue

        m = COMPACT_LINE_RE.match(line)
        if not m:
            continue

        version = m.group("version")
        path = m.group("path")
        line_no = int(m.group("line"))
        content = m.group("content").rstrip()

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
```

**Notes** :

- L'accumulateur intermédiaire `versions_acc` reste un `dict[str, dict[str, list[Hit]]]` mutable, **local à la fonction**, pour bénéficier de l'ordre d'insertion garanti Python 3.7+ et de l'idiome `setdefault`. La conversion vers `ParsedResults` immuable est faite en sortie, en un seul passage.
- Plus de retour `(None, summary)` pour signaler l'absence de hits. Le renderer teste `if parsed_results.versions:` au lieu de `if parsed is not None:`. Plus explicite, moins de cas spéciaux.
- Côté HTML : tous les sites d'appel (`empty_template`, route `/search`) sont adaptés en conséquence.

### 3.2 Mutualisation `/search` ↔ `/export`

Avant v0.3.0, `parse_compact_output()` était invoquée uniquement par `/search`. v0.3.0 l'appelle également dans `/export`, avec exactement le même comportement (bypass en mode contexte). Une seule passe de parsing, deux renderers consommateurs.

### 3.3 Généralisation de `markdown_inline_code()`

**Avant** (`webapp.py` v0.2.1) :

```python
def markdown_inline_code(value: str) -> str:
    if "`" not in value:
        return f"`{value}`"
    return f"`` {value} ``"
```

**Après** :

```python
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
```

**Notes** :

- Cohérent avec la règle CommonMark : la fence inline doit être strictement plus longue que toute séquence interne.
- Le padding par espace est conservé du comportement v0.2.1 mais conditionné aux bords (économie d'espaces parasites dans la sortie).
- `re` est déjà importé.

### 3.4 Nouvelle fonction `render_markdown_results()`

Ajouter après `parse_compact_output()` :

```python
def render_markdown_results(parsed: ParsedResults, fallback_stdout: str) -> str:
    """Rend la section ## Results en Markdown structuré.

    - parsed.versions non vide → hiérarchie version > path > hits.
    - parsed.versions vide et fallback_stdout non vide/sentinelle → code fence brut (mode contexte).
    - parsed.versions vide et fallback_stdout vide ou "No results." → "_No results._".
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

    fence = markdown_fence_for(fallback_stdout)
    block = fallback_stdout if fallback_stdout.endswith("\n") else f"{fallback_stdout}\n"
    return f"## Results\n\n{fence}text\n{block}{fence}\n"
```

### 3.5 Nouvelle fonction `render_markdown_summary()`

```python
def render_markdown_summary(summary: Summary | None) -> str:
    """Rend la section ## Summary, toujours présente.

    summary None → bloc rendu avec ligne diagnostic `- Summary parsing: failed`.
    summary présent → bloc rendu nominalement.
    """
    if summary is None:
        return "## Summary\n\n- Summary parsing: `failed`\n\n"
    return (
        "## Summary\n"
        "\n"
        f"- Results: {markdown_inline_code(str(summary.count))}\n"
        f"- Versions: {markdown_inline_code(str(summary.versions))}\n"
        f"- Duration: {markdown_inline_code(summary.duration + ' s')}\n"
        "\n"
    )
```

**Note observabilité (révision de §2.2 du draft initial)** : le bloc `## Summary` n'est plus omis silencieusement en cas d'échec de parsing du footer. Il devient un point de diagnostic explicite. Justification :

- Le silence v0.2.x masquait un drift moteur sans signal.
- Un drift de wording dans `engine.py` (libellé footer, ponctuation, symbole `•`) provoquait la disparition des badges sans erreur visible — le renderer dégradait silencieusement.
- v0.3.0 affiche `Summary parsing: failed` dans le bloc `## Summary`. Discret (pas un blockquote `> Warning`), mais lisible (formaté comme une ligne du bloc, casse cohérente).
- Côté HTML : non répliqué pour l'instant. Le badge row reste muet en cas d'échec. À traiter en v0.3.1 si besoin (cf. §12).

**Effet sur les cas vides** : pour un export `_No results._`, le footer moteur est toujours présent dans le stdout brut (le moteur émet `0 results across 0 versions • duration X s` même quand il n'y a rien). Donc `Summary` non None dans ce cas, bloc `## Summary` rendu nominalement avec `0` / `0` / `X s`. Pas de cas "vides + summary failed" attendu en pratique.

### 3.6 Nouvelle fonction `render_markdown_query()`

Extraction du bloc en-tête, pour clarté :

```python
def render_markdown_query(query: str, options: dict[str, bool]) -> str:
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
```

**Note** : le champ `Context: yes/no` du format v0.2.x est remplacé par `Mode: compact/context`. C'est plus lisible et cohérent avec le flag CLI `--mode`. Le CHANGELOG documente ce changement (breaking côté lecteur humain, pas côté lecteur machine puisqu'il n'y a pas de consommateur machine du `.md`).

### 3.7 Refonte de `build_markdown_export()`

**Avant** (v0.2.1) :

```python
def build_markdown_export(query: str, options: dict[str, bool], stdout: str) -> str:
    fence = markdown_fence_for(stdout)
    stdout_block = stdout if stdout.endswith("\n") else f"{stdout}\n"
    return (
        "# ha-archive-search — Results\n"
        "\n"
        f"- Query: {markdown_inline_code(query)}\n"
        # ...
        f"{fence}text\n"
        f"{stdout_block}"
        f"{fence}\n"
        "\n"
        "---\n"
        "Export generated by ha-archive-search\n"
    )
```

**Après** :

```python
def build_markdown_export(query: str, options: dict[str, bool], stdout: str) -> str:
    if not options.get("context"):
        parsed = parse_compact_output(stdout)
    else:
        # Mode contexte : pas de parsing structurel des hits.
        # Tenter d'extraire le summary du footer en isolation (best-effort).
        summary: Summary | None = None
        for raw_line in stdout.splitlines():
            m = SUMMARY_RE.fullmatch(raw_line.rstrip("\n"))
            if m:
                summary = Summary(
                    count=int(m.group("count")),
                    versions=int(m.group("versions")),
                    duration=m.group("duration").replace(",", "."),
                )
                break
        parsed = ParsedResults(versions=(), summary=summary)

    parts = [
        "# ha-archive-search — Results",
        "",
        render_markdown_query(query, options),
        render_markdown_summary(parsed.summary),
        render_markdown_results(parsed, stdout),
        "\n---\n",
        f"Export generated by ha-archive-search v{__version__}\n",
    ]
    return "".join(parts)
```

**Note sur l'import de `__version__`** : ajouter en tête de `webapp.py` :

```python
from ha_archive_search import __version__
```

**Note sur le mode contexte** : `parsed.versions` est un tuple vide, ce qui dirige `render_markdown_results()` vers la branche fence brut. `parsed.summary` reste best-effort. Le diagnostic `Summary parsing: failed` s'affichera si le footer du mode contexte ne correspond pas à `SUMMARY_RE` — c'est le comportement attendu et il révèle un drift éventuel.

### 3.8 Route `/export` — comportement

La route `/export` elle-même **ne change pas**. Elle continue d'appeler `build_markdown_export(query, options, result.stdout)`. Tout le travail est dans la refonte interne de `build_markdown_export()`. Le nom du fichier, les headers HTTP, les codes d'erreur sont strictement préservés.

### 3.9 Route `/search` — adaptations au modèle typé

La route `/search` doit être adaptée pour consommer `ParsedResults` au lieu du tuple `(dict | None, dict | None)`. Diff :

**Avant** :

```python
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

**Après** :

```python
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
```

`empty_template` passe désormais `parsed` (un `ParsedResults`) au lieu de `parsed` + `summary` séparés. Le summary est accédé via `parsed.summary` dans le template.

### 3.10 Préservation du footer applicatif

Le footer `Export generated by ha-archive-search` est étendu pour inclure la version (`v0.3.0`). Cela permet à un lecteur (humain ou LLM) de savoir quel format de structuration est appliqué, sans inspecter l'en-tête du fichier.

---

## 4. `templates/index.html` — modifications

Le template HTML doit être adapté pour consommer le modèle typé `ParsedResults` (cf. §1.6 et §3.1). Le rendu visuel produit doit rester **fonctionnellement équivalent** à v0.2.0.

### 4.1 Boucle versions/fichiers/hits

**Avant** (v0.2.0) :

```jinja
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
```

**Après** :

```jinja
{% for v in parsed.versions %}
  <div class="version-block">
    <div class="version-title">{{ v.version }}</div>
    {% for f in v.files %}
      <details class="file-block" open>
        <summary>
          <span class="file-path">{{ f.path }}</span>
          <span class="file-count">{{ f.hits|length }} occurrence{% if f.hits|length > 1 %}s{% endif %}</span>
        </summary>
        <div class="hits">
          {% for hit in f.hits %}
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
```

### 4.2 Garde d'affichage

**Avant** :

```jinja
{% if parsed %}
  <section class="result-panel block">
```

**Après** :

```jinja
{% if parsed.versions %}
  <section class="result-panel block">
```

Conséquence : `parsed` n'est plus `None`, mais un `ParsedResults` avec `versions=()` quand aucun hit n'a été parsé. Le test booléen sur `parsed.versions` (tuple vide → falsy) déclenche le même fallback `<pre>` qu'avant.

### 4.3 Bloc summary

**Avant** :

```jinja
{% if summary %}
  <div class="summary">
    <span class="badge">{{ summary.count }} results</span>
    <span class="badge">{{ summary.versions }} version{% if summary.versions != "1" %}s{% endif %}</span>
    <span class="badge">{{ summary.duration }} s</span>
  </div>
{% endif %}
```

**Après** :

```jinja
{% if parsed.summary %}
  <div class="summary">
    <span class="badge">{{ parsed.summary.count }} results</span>
    <span class="badge">{{ parsed.summary.versions }} version{% if parsed.summary.versions != 1 %}s{% endif %}</span>
    <span class="badge">{{ parsed.summary.duration }} s</span>
  </div>
{% endif %}
```

Notes :

- `parsed.summary` au lieu de `summary` (variable séparée supprimée).
- Comparaison `!= 1` (int) au lieu de `!= "1"` (str), conséquence du typage `Summary.versions: int`.

### 4.4 Test de non-régression visuel

Critère : sur une même query et un même état d'archive, le rendu HTML v0.3.0 et le rendu v0.2.0 doivent présenter une **équivalence fonctionnelle et visuelle** — mêmes blocs visibles, mêmes textes affichés, même structure de navigation, même apparence CSS. Les divergences au niveau du DOM brut (ordre attributaire, whitespace inter-balises, fragments générés par Jinja qui ne se voient pas à l'écran) ne constituent pas une régression tant qu'elles ne sont ni perceptibles à l'œil ni accrochées par un sélecteur CSS existant. C'est le test 11.13.

### 4.5 Invariant de cohérence cross-renderer

Le rendu HTML `/search` et le rendu Markdown `/export` consomment exactement le même objet `ParsedResults` issu de la même invocation de `parse_compact_output()`. Toute évolution future du parser bénéficie aux deux sorties simultanément. Toute dérive du wording moteur (cf. note v0.2.0 sur `SUMMARY_RE`) impacte les deux de façon symétrique : badges HTML absents + diagnostic Markdown `Summary parsing: failed`.

---

## 5. `docs/contrat_webapp.md` — amendement

### 5.1 Section `/export route` → `Output format`

Remplacer le bloc actuel par :

```markdown
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
```

### 5.2 Section `/export route` → `Consistency with the CLI engine contract`

Remplacer par :

```markdown
### Consistency with the CLI engine contract

The CLI engine contract lists among its non-goals: "structured Markdown export". This non-goal applies to the **engine** — the engine never emits structured Markdown.

The webapp Markdown export, since v0.3.0, is structured. The structuring is performed by the **presentation layer**, by parsing the engine's compact stdout via `parse_compact_output()`. The parser produces a typed immutable model (`ParsedResults`) consumed by both the HTML and Markdown renderers. No structured output format is required from the engine.

Renderer boundary:

- **Admitted**: deterministic structural aggregation derived from information already present in the stdout — grouping by version, grouping by file, per-file occurrence count, footer summary extraction, Markdown-safe encapsulation.
- **Forbidden**: any form of semantic or historical inference — classification, ranking, filtering, multi-version correlation, first-seen / last-seen tracking, diff computation. Such capabilities, if introduced, belong to a separate intelligence layer above the typed model (out of scope for v0.3.0, see `vision_domaine.md`).
```

### 5.3 Section non-goals v1

Ajuster la liste des non-goals v1 :

**Retirer** :

- `structured export (by version / file / match)` — devenu un goal en v0.3.0.

**Conserver** :

- `export history`;
- `host storage of exports`;
- `PDF, DOCX, or ZIP export`;
- `HTML export`;
- `scheduled export generation`;
- `historical intelligence (first seen / last seen / multi-version presence)` — *préciser que ceci reste hors périmètre, géré par une future couche dédiée.*

### 5.4 Section versionnage du contrat

Ajouter une entrée :

```markdown
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
```

---

## 6. Version bump

### 6.1 `pyproject.toml`

```toml
version = "0.3.0"
```

### 6.2 `src/ha_archive_search/__init__.py`

```python
from ha_archive_search.engine import (
    Match,
    SearchResult,
    main,
)

# Internal typed model — exposed for testability.
# No backward compatibility guarantee before v1.0.
from ha_archive_search.webapp import (
    Hit,
    FileResult,
    VersionResult,
    Summary,
    ParsedResults,
)

__version__ = "0.3.0"

__all__ = [
    "Match",
    "SearchResult",
    "main",
    "__version__",
    # Internal model — see comment above.
    "Hit",
    "FileResult",
    "VersionResult",
    "Summary",
    "ParsedResults",
]
```

**Note sur la surface publique** : exposer les dataclasses dans `__all__` est délibéré pour permettre des tests unitaires externes au module `webapp`. La mention `Internal typed model — No backward compatibility guarantee before v1.0` est explicite et doit rester visible dans le fichier source. Le CHANGELOG porte également cette précision. Toute personne qui importe ces classes accepte implicitement qu'elles puissent muter d'une release mineure à l'autre avant v1.0.

---

## 7. `CHANGELOG.md` — entrée v0.3.0

Ajouter en tête du fichier, avant l'entrée `[0.2.1]` :

```markdown
## [0.3.0] — 2026-XX-XX

### Changed

#### Webapp — Markdown export (breaking format change)

- `webapp.py`: `/export` now produces a **structured Markdown** document.
  - `## Query` block: term, mode, latest, all-versions, documentation scope, export date.
  - `## Summary` block: result count, version count, duration. If the engine footer is not parsable, the block is still emitted with a diagnostic line `- Summary parsing: failed` (observability over silence).
  - `## Results` block: per-version `###` headings, per-file `####` headings with occurrence count, per-hit bullet list (`- **L<line>** — <content>`).
  - Empty result set rendered as `_No results._` under `## Results`.
  - Context mode preserves a raw fenced fallback under `## Results`.
- `webapp.py`: `build_markdown_export()` rewritten to consume `ParsedResults`.
- `webapp.py`: new helpers `render_markdown_query()`, `render_markdown_summary()`, `render_markdown_results()`.
- `webapp.py`: `markdown_inline_code()` generalized to handle arbitrary-length backtick runs in payloads.
- `webapp.py`: footer line `Export generated by ha-archive-search v<version>` now includes the package version.
- Query block field renamed: `Context: yes/no` → `Mode: compact/context`.

#### Webapp — typed internal model

- `webapp.py`: introduction of frozen dataclasses as the contract between `parse_compact_output()` and renderers.
  - `Hit(line: int, content: str)`.
  - `FileResult(path: str, hits: tuple[Hit, ...])`.
  - `VersionResult(version: str, files: tuple[FileResult, ...])`.
  - `Summary(count: int, versions: int, duration: str)`.
  - `ParsedResults(versions: tuple[VersionResult, ...], summary: Summary | None)`.
- `webapp.py`: `parse_compact_output()` now returns `ParsedResults` instead of `tuple[dict | None, dict | None]`. Empty result set returns `ParsedResults(versions=(), summary=...)`, no `None` sentinel.
- `templates/index.html`: adapted to consume `ParsedResults`. HTML output strictly identical to v0.2.0 on equivalent inputs (non-regression test).
- `__init__.py`: dataclasses re-exported for testability under an explicit *internal model, no backward compatibility guarantee before v1.0* marker.

### Added

- Shared use of `parse_compact_output()` and the typed model across `/search` and `/export`. Both routes consume the same parser output; any engine-side wording drift affects both consistently and visibly.
- Diagnostic observability for footer parse failure: `Summary parsing: failed` rendered in Markdown export (HTML badge row remains silent for now; deferred).

### Unchanged

- `engine.py`: no change. No new CLI flag, no new output format, no JSON mode.
- `/export` HTTP contract: route, validation rules, file naming, headers, error codes — all preserved.
- `/search` HTTP and visual contract: DOM output strictly identical to v0.2.0.
- Engine authority: webapp adds no grep logic, no filtering, no ranking, no historical correlation.

### Contract

- `docs/contrat_webapp.md`: amended. Markdown export section rewritten. v1 non-goal "structured export" removed. Renderer doctrine reformulated: structural aggregation (grouping, counting per file) is admitted; semantic or historical inference remains forbidden.
- Historical intelligence (first-seen / last-seen / multi-version diff) remains explicitly out of scope.
```

---

## 8. `README.md` — section export

### 8.1 Bloc à modifier

Localiser la section décrivant `/export` (mention du téléchargement Markdown) et substituer un exemple structuré au descriptif "raw stdout wrapped in a code fence".

### 8.2 Texte de remplacement

```markdown
## Markdown export

`POST /export` produces a structured Markdown document derived from the engine output. Layout:

- `## Query` — search parameters and export timestamp.
- `## Summary` — result count, version count, duration (engine footer). Always present: if the engine footer is not parsable, the block is emitted with a `Summary parsing: failed` diagnostic line.
- `## Results` — per-version sections, per-file subsections with occurrence counts, per-hit bullets.

File naming: `ha_archive_search_<slug>_<YYYY-MM-DD_HH-MM>.md`.

The export is generated in memory and streamed as `text/markdown; charset=utf-8`. No file is written on the host.

Context mode falls back to a raw fenced block under `## Results`. The `## Summary` block follows the same diagnostic rule.

Empty results: a single `_No results._` line under `## Results`. `## Summary` is still emitted, either nominally if the engine produced a zero-result footer, or with the diagnostic line otherwise.
```

---

## 9. Renderer doctrine (rappel et étendue)

Doctrine v0.2.0 étendue à la couche Markdown, avec reformulation :

- Le stdout du moteur CLI reste la source de vérité.
- `parse_compact_output()` ne corrige pas, ne filtre pas, ne réordonne pas.
- Le renderer pratique de l'**agrégation structurelle** : groupement par version, par fichier, compteur d'occurrences par fichier. C'est de la mise en forme à partir de l'information déjà présente dans le stdout, pas de l'inférence.
- Le renderer ne pratique **aucune interprétation sémantique ou historique** : pas de classification de hits, pas de détection de patterns, pas de corrélation inter-versions, pas de first-seen / last-seen, pas de diff. Ces capacités appartiennent à une couche d'intelligence séparée (hors périmètre v0.3.0, cf. §12).
- Pas de cache d'export. `parsed` est local à la requête `/export`.
- Le renderer Markdown est best-effort, comme son jumeau HTML. En cas d'échec de parsing des hits, le fallback fence brut reste la référence authoritative. En cas d'échec de parsing du footer, le diagnostic explicite `Summary parsing: failed` est rendu — observabilité avant esthétique.

**Reformulation de la frontière** : la phrase "aucune dérivation" du draft v0.3.0 initial était trop catégorique. Le compteur `N occurrences` est une dérivation. La frontière exacte est : *toute agrégation déterministe sur le contenu structurel du stdout est admise ; toute inférence sémantique ou historique est interdite*.

---

## 10. Scalabilité future

Pour le plafond moteur actuel (2000 résultats), l'export Markdown structuré reste raisonnable (estimé < 1 Mo, généré en mémoire). Au-delà, le format devient un flux plutôt qu'un document. Cette section liste les pistes **hors périmètre v0.3.0** mais explicitement reconnues, pour ne pas laisser un angle mort.

### 10.1 Pistes envisagées

- **TOC en tête** : table des matières automatique listant les versions présentes, avec ancres Markdown. Utile au-delà de 5 versions.
- **Collapse strategy** : marqueurs `<details>`/`<summary>` HTML inline dans le Markdown pour les fichiers à très grand nombre de hits. CommonMark autorise le HTML inline. Compatible GitHub, GitLab, la plupart des lecteurs.
- **Per-version truncation** : limite N hits affichés par fichier avec marqueur `… (X autres hits, voir export brut)`. Préserve la lisibilité.
- **Split exports** : un fichier `.md` par version pour les exports `--all-versions`, livrés en `.zip`. Suppose abandon du non-goal "ZIP export" — décision contractuelle.
- **Streaming export** : rendu Markdown au fil du stdout moteur, transmis en streaming HTTP. Suppose `subprocess.Popen` au lieu de `subprocess.run`, ce qui complique la gestion du timeout et du lock.
- **Grouped summaries** : agrégation par version (`## Summary` per `### <version>` avec compteur local). Reste de l'agrégation structurelle, pas de l'inférence — cohérent avec la doctrine §9.

### 10.2 Critère de déclenchement

Pas de seuil chiffré pour l'instant. La décision sera prise à la première remontée terrain d'un export jugé "monstrueux". v0.3.0 livre la base structurée ; v0.3.x ou v0.4.0 traitera la scalabilité si le besoin émerge.

### 10.3 Ce qui est volontairement non traité en v0.3.0

- Pas de TOC.
- Pas de collapse `<details>` dans le Markdown.
- Pas de troncature côté renderer (le plafond moteur reste la seule limite).
- Pas de split. Un export = un fichier.
- Pas de streaming.

Le renderer v0.3.0 produit un document linéaire complet. Si le volume devient un problème, la stratégie sera choisie en connaissance de cause, pas dans l'urgence.

---

## 11. Vérification avant release

Checklist séquentielle :

### 11.1 Parsing partagé et modèle typé

- [ ] `parse_compact_output()` retourne `ParsedResults` typé sur les deux routes.
- [ ] Aucune duplication de regex entre `/search` et `/export`.
- [ ] Dataclasses `Hit`, `FileResult`, `VersionResult`, `Summary`, `ParsedResults` exportées par `__init__.py` (testabilité).
- [ ] `__init__.py` porte le commentaire `Internal typed model — No backward compatibility guarantee before v1.0`.
- [ ] `frozen=True` effectif : tentative de mutation lève `dataclasses.FrozenInstanceError`.

### 11.2 Mode compact, résultats non vides

- [ ] Requête type → fichier `.md` téléchargé.
- [ ] Présence du `# ha-archive-search — Results` en H1.
- [ ] Bloc `## Query` complet (6 lignes : term, mode, latest, all_versions, documentation, date).
- [ ] Bloc `## Summary` présent, valeurs cohérentes avec le footer moteur.
- [ ] Bloc `## Results` présent, hiérarchie `###` / `####` / `-` respectée.
- [ ] Compteur `N occurrence(s)` par fichier — pluriel correct (singulier si N=1).
- [ ] Ordre des versions, fichiers, hits identique au stdout moteur.

### 11.3 Mode compact, résultats vides

- [ ] Vérifier le stdout moteur réel pour zéro hit : émet-il `0 results across 0 versions • duration X s` ou la sentinelle `No results.` ?
- [ ] Si footer émis : `## Summary` rendu avec zéros ; `## Results` contient `_No results._`.
- [ ] Si sentinelle uniquement : `## Summary` rendu avec `Summary parsing: failed` ; `## Results` contient `_No results._`.
- [ ] Aucune hiérarchie `###` ou `####`.

### 11.4 Mode contexte

- [ ] Bloc `## Results` contient un code fence `text` avec le stdout moteur brut.
- [ ] Si le footer moteur est parsable : `## Summary` rendu nominalement.
- [ ] Si le footer n'est pas parsable : `## Summary` rendu avec `Summary parsing: failed` — observable, pas silencieux.
- [ ] Compatibilité visuelle avec l'export v0.2.x pour ce mode (pas de régression de lisibilité).

### 11.5 Échappement Markdown

- [ ] Path contenant `_`, `.`, `/` rendu en code inline sans casser le rendu Markdown.
- [ ] Hit `content` contenant `` ` `` rendu avec fence backtick adaptative.
- [ ] Hit `content` contenant `` `` `` (double backtick) rendu avec fence triple ou plus, sans collision.
- [ ] Version commençant ou finissant par `` ` `` (cas pathologique) → espaces de garde insérés.
- [ ] `markdown_inline_code("")` retourne `` `` `` (deux backticks), pas une exception.

### 11.6 Header HTTP

- [ ] `Content-Type: text/markdown; charset=utf-8`.
- [ ] `Content-Disposition: attachment; filename="ha_archive_search_<slug>_<timestamp>.md"`.
- [ ] Nom de fichier strictement identique à v0.2.x (slug + timestamp).

### 11.7 Comportement d'erreur

- [ ] Query vide → 400, message HTML inline, aucun fichier livré.
- [ ] Options incompatibles → 400, message HTML inline.
- [ ] Engine exit non-zéro → 502, message HTML inline.
- [ ] Timeout → 504, message HTML inline.

### 11.8 Idempotence et stabilité

- [ ] Deux exports successifs avec la même query produisent le même Markdown (hors timestamp `Export date`).
- [ ] Tri stable : pas de variation d'ordre entre runs.
- [ ] Diff binaire de deux exports successifs : différence uniquement sur la ligne `Export date` du bloc `## Query`.

### 11.9 Cohérence cross-renderer

- [ ] Le rendu HTML `/search` et le rendu Markdown `/export` produits sur la même query montrent la même hiérarchie (mêmes versions, mêmes fichiers, mêmes hits, même ordre).
- [ ] Le compteur `Summary` est strictement identique entre HTML et Markdown.
- [ ] Le rendu HTML v0.3.0 (sur `ParsedResults` typé) présente une équivalence visuelle et fonctionnelle avec le rendu v0.2.0 (sur `dict` libre) pour les mêmes données d'entrée.

### 11.10 Versionnage

- [ ] `pyproject.toml` → `version = "0.3.0"`.
- [ ] `__init__.py` → `__version__ = "0.3.0"`.
- [ ] Footer Markdown → `Export generated by ha-archive-search v0.3.0`.
- [ ] CHANGELOG → entrée `[0.3.0]` en tête, datée.

### 11.11 Contrat

- [ ] `docs/contrat_webapp.md` : section `/export` → `Output format` réécrite.
- [ ] `docs/contrat_webapp.md` : section `Consistency with the CLI engine contract` mise à jour.
- [ ] `docs/contrat_webapp.md` : non-goal "structured export" retiré de v1.
- [ ] `docs/contrat_webapp.md` : entrée versionnage v0.3.0 ajoutée.

### 11.12 README

- [ ] Section export Markdown réécrite avec le nouveau layout.

### 11.13 Non-régression

- [ ] `/search` : rendu HTML v0.3.0 fonctionnellement et visuellement équivalent à v0.2.0 sur jeu de test fixé.
- [ ] `engine.py` : aucun diff.
- [ ] `Dockerfile` et `docker-compose*.yml` : aucun diff.
- [ ] `/health` : réponse JSON inchangée.

---

## 12. Ce qui n'est pas dans cette release

Périmètre explicitement exclu de v0.3.0 :

- **`--output-format json` côté moteur CLI** — non requis, le parser regex sur stdout compact suffit pour les deux renderers.
- **Mode contexte structuré** — initialement fléché v0.3.0 par `RELEASE_0_2_0.md`, reporté. Le mode contexte conserve un fallback fence brut. La structuration multi-lignes du mode contexte requiert un parser dédié non livré ici. Périmètre v0.4.0 ou ultérieur.
- **Intelligence historique** — first seen / last seen / présence multi-versions / diff inter-versions. Toujours hors périmètre, géré par une couche dédiée future.
- **Export HTML, PDF, DOCX, ZIP** — non.
- **Historique d'export, cache, stockage hôte** — non.
- **Génération planifiée d'exports** — non.
- **Front-end JavaScript** — hors doctrine.
- **Authentification applicative** — hors doctrine (périmètre LAN/VPN).

---

## 13. Risques et notes de portage

### 13.1 Rupture de format pour les consommateurs en aval

Tout outil qui consommait jusqu'ici le `.md` v0.2.x comme un simple wrapper autour du stdout brut (par exemple : grep sur le contenu du fichier exporté, ou ingestion LLM sans parsing Markdown) verra une structure différente :

- Les lignes `[<version>] <path>:<line>:<content>` ne sont plus présentes telles quelles.
- Le contenu équivalent est désormais distribué entre `### <version>`, `#### <path>`, et `- **L<line>** — <content>`.

Un consommateur qui souhaite récupérer le stdout brut peut toujours le générer en mode contexte : le fallback fence préserve le format ligne-par-ligne. C'est un workaround documenté, pas une garantie contractuelle pour les futures releases.

### 13.2 Dépendance au wording moteur

`SUMMARY_RE` reste accroché au wording anglais du footer compact (`results across N versions • duration X s`). Cette dépendance est désormais partagée par deux renderers au lieu d'un. Toute modification du wording moteur dégrade les renderers de façon **asymétrique** en v0.3.0 :

- côté Markdown : bloc `## Summary` rendu avec `- Summary parsing: ` `` `failed` `` — **diagnostic explicite, observable à la lecture du fichier**.
- côté HTML : badges row absente, hiérarchie intacte — **dégradation silencieuse**, observable seulement par comparaison visuelle avec un état antérieur.

Cette asymétrie est un défaut connu de v0.3.0. La symétrisation (badge HTML "summary unavailable" ou équivalent) est reportée v0.3.1.

Le contrat moteur CLI doit préserver le wording footer, ou les deux contrats parsers doivent être mis à jour conjointement avec une bascule visible dans le CHANGELOG.

### 13.3 Encodage UTF-8

Le `.md` est servi en `text/markdown; charset=utf-8`. Les noms de version Home Assistant contiennent typiquement de l'ASCII pur. Les contenus de hit peuvent contenir de l'UTF-8 (commentaires français, accents). Pas de transformation, pas de re-encodage côté webapp.

### 13.4 Taille de fichier

L'export structuré est strictement plus volumineux que l'export brut (overhead des markers `###`, `####`, `- **L...**`, fences inline). Pour le plafond moteur (2000 résultats), l'estimation reste inférieure à 1 Mo en pratique. Toujours généré en mémoire, pas de streaming. Les stratégies envisagées pour les très gros volumes sont listées au §10.

### 13.5 Surface publique du package

Le §1.6 introduit des dataclasses (`Hit`, `FileResult`, `VersionResult`, `Summary`, `ParsedResults`) exportées via `__init__.py`. Cette décision augmente implicitement la surface publique du package : des consommateurs externes pourraient commencer à importer `from ha_archive_search import ParsedResults`.

**Position contractuelle** : ces dataclasses sont un **modèle interne**, exposé pour la testabilité (notamment pour permettre des tests unitaires en dehors du module `webapp`). Elles ne sont pas un contrat public stable avant v1.0.

Le `__init__.py` doit porter explicitement la mention :

```python
# Internal typed model — exposed for testability.
# No backward compatibility guarantee before v1.0.
```

Et le `__all__` doit refléter cette intention sans masquer l'exposition. Le CHANGELOG v0.3.0 mentionne cette zone grise.

---

## 14. Récapitulatif des diffs

| Fichier | Nature du diff |
|---|---|
| `webapp.py` | Introduction du modèle typé (`Hit`, `FileResult`, `VersionResult`, `Summary`, `ParsedResults`). Refonte `parse_compact_output()` → retour `ParsedResults`. Refonte `build_markdown_export()`. Généralisation `markdown_inline_code()`. Ajout `render_markdown_query()` / `render_markdown_summary()` / `render_markdown_results()`. Adaptation de la route `/search`. Import `__version__`. |
| `templates/index.html` | Adaptation au modèle typé : `parsed.versions`, `f.path`, `f.hits`, `hit.line`, `hit.content`, `parsed.summary`. Rendu visuel identique. |
| `__init__.py` | Bump `__version__` → `"0.3.0"`. Export des dataclasses dans `__all__` pour testabilité externe. |
| `pyproject.toml` | Bump `version` → `"0.3.0"`. |
| `CHANGELOG.md` | Entrée `[0.3.0]` en tête. |
| `README.md` | Section export Markdown réécrite. |
| `docs/contrat_webapp.md` | Section `/export` amendée, non-goals v1 ajustés, entrée versionnage v0.3.0. |
| `docs/RELEASE_0_3_0.md` | Le présent document. |

---

## 15. Note doctrinale : positionnement du projet

À l'origine, `ha-archive-search` est un outil d'infrastructure : grep sur archives, sortie stdout, périmètre LAN. v0.2.0 a introduit un renderer HTML structuré. v0.3.0 introduit un renderer Markdown structuré et un modèle interne typé.

Cumulativement, ces deux étapes constituent un **glissement assumé** : d'un outil grep-oriented vers une **couche de lecture structurée d'archives Home Assistant**, exploitable par un lecteur humain comme par un consommateur LLM en aval.

Conséquences à terme :

- Le parser regex sur stdout compact atteindra ses limites. La pression viendra des nouveaux modes de rendu, pas du moteur.
- Le modèle interne typé introduit en v0.3.0 devient un point d'ancrage pour les évolutions futures (`first_seen`, `last_seen`, diff inter-versions, etc.) : ces capacités s'y greffent naturellement, sans toucher au moteur.
- Le contrat moteur CLI restera, autant que possible, l'autorité textuelle. Si une couche d'intelligence devient nécessaire, elle devrait se construire au-dessus du modèle typé v0.3.0, pas à l'intérieur du moteur.

Le document ne prétend pas que "ce n'est qu'un renderer". v0.3.0 *est* un renderer ; mais c'est aussi la première brique d'un consommateur structuré qui ne dit pas encore son nom. Le nommer ici sert à éviter qu'il s'installe par dérive silencieuse.

### 15.1 Migration probable du modèle vers un module dédié

`webapp.py` v0.3.0 cumule maintenant huit responsabilités distinctes : routes Flask, validation de formulaire, invocation du moteur CLI via subprocess, parser regex, modèle typé, helpers d'échappement Markdown, renderer Markdown, préparation des données pour le renderer HTML (via le template Jinja). C'est encore lisible dans un seul fichier d'environ 400 lignes, mais la trajectoire ne tient pas indéfiniment.

À une release ultérieure — pas en v0.3.0, sans engagement de calendrier — il deviendra probablement souhaitable d'extraire :

- `src/ha_archive_search/models.py` ou `types.py` : les dataclasses (`Hit`, `FileResult`, `VersionResult`, `Summary`, `ParsedResults`).
- `src/ha_archive_search/parser.py` : la fonction `parse_compact_output()`, ses regex `COMPACT_LINE_RE` et `SUMMARY_RE`, et tout futur parser dérivé.
- `src/ha_archive_search/renderers/markdown.py` : les fonctions `render_markdown_*` et `markdown_inline_code()`.
- `src/ha_archive_search/webapp.py` : strictement les routes Flask, la validation et l'invocation moteur.

Cette migration n'introduit aucune capacité nouvelle. Son rôle est d'aligner le découpage fichier sur le découpage de responsabilités déjà acté dans la doctrine. Elle deviendra nécessaire quand l'un des trois signaux suivants apparaîtra :

- un deuxième parser (mode contexte structuré, ou parser pour un nouveau format moteur),
- un deuxième renderer non trivial (JSON, OpenSearch, autre),
- ou simplement le seuil empirique où relire `webapp.py` devient pénible.

v0.3.0 ne fait pas cette migration. La signaler ici sert le même but que §15 dans son ensemble : nommer un glissement probable pour qu'il soit choisi, pas subi.
