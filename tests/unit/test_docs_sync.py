"""Drift tests: the documents describe what ``src/`` has, and nothing more.

``src/`` is the reference. A document that names a path, a module, a class, a
method, a verb, a ``kind``, a ``pixi run`` task or an ``htas`` command that
``src/`` (or the repository) does not have fails here, in the change that
made the two disagree. The doc-impact map in ``htas-dev.md`` says which
documents a change must update; these tests catch the ones it missed.

What is checked, in every Markdown document (README, ``docs/*.md``,
``tests/README.md``) and in every LaTeX and Slidev file of the user guide
(``docs/hydrological_twin``, skipped when that repository is absent):

- inline code (Markdown backticks, LaTeX ``\\texttt``/``\\verb``): every path
  exists, and every Python name is defined somewhere in ``src/``;
- code blocks: Python imports resolve, calls name real methods and real
  keyword arguments, ``kind=`` values are real kinds of their verb, and
  ``pixi run``/``htas`` lines name real tasks and commands;
- every count of macro-verbs written in prose equals the real number;
- relative Markdown links resolve.

A chapter of the White Book that describes the HydrologicalTwin *target*,
which HTAS does not implement, carries ``\\htastarget``. Only there may it use
the target's vocabulary, and only the names listed in ``TARGET_NAMES``.
Everything it says about HTAS itself is checked like any other document.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import importlib
import inspect
import re
import textwrap
import tomllib
from functools import lru_cache
from pathlib import Path

import pytest

from HydrologicalTwinAlphaSeries.cli import COMMANDS
from HydrologicalTwinAlphaSeries.ht.client import HydrologicalTwinClient
from HydrologicalTwinAlphaSeries.ht.developer import HydrologicalTwin
from HydrologicalTwinAlphaSeries.ht.developer.api_types import MINIMUM_STATE

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "src" / "HydrologicalTwinAlphaSeries"
GUIDE = ROOT / "docs" / "hydrological_twin"
README = ROOT / "README.md"
README_MAX_LINES = 250
TARGET_LABEL = "\\htastarget"

_SKIP_DIRS = {".git", ".pixi", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".agent"}

# Names a document may use without src defining them: the language, the
# libraries HTAS is built on, the tools that run it, and CaWaQS's own words.
EXTERNAL_NAMES = {
    *dir(builtins),
    "python", "pip", "pixi", "pytest", "ruff", "git", "pre", "commit", "cgitsync",
    "numpy", "np", "pandas", "pd", "geopandas", "gpd", "matplotlib", "plotly", "shapely",
    "DataFrame", "GeoDataFrame", "Series", "ndarray", "datetime64", "datetime",
    "Path", "pathlib", "json", "toml", "tomllib", "dataclass", "dataclasses", "enum",
    "Dict", "List", "Optional", "Any", "self", "cls", "kwargs", "args",
    "CaWaQS", "QGIS", "qgis", "PyQt", "PyQt5", "GitHub", "GitLab",
    "OUT_CAW", "CWAQS_FIXTURE_ROOT", "CGSHOME", "HEAD",
    "SemVer", "MAJOR", "MINOR", "PATCH", "main", "branch", "gitmodules",
}

# The HydrologicalTwin target's vocabulary, which HTAS does not implement.
# Only a chapter labelled \htastarget may use these names.
TARGET_NAMES = {
    "GitSynchroRecord", "HydroTwin", "SubTwin", "subTwin", "IdCard", "Software", "Simulation",
    "Rendering", "public", "private", "rendering", "self_fitting", "verify_metadata",
    "verify_key", "git_synchro", "git_push", "git_commit", "extract_values", "append_validated",
    "tolerance", "max_iterations", "objective_function_value", "CalibrationResult",
    "temporal_bayesian_inference", "multi_stage_bayesian", "pso", "mcmc", "gradient_descent",
    "enkf", "custom", "scientific_certificate", "none", "dirty", "ok", "modelName", "version",
    "branch", "commit_hash", "epsilon", "compilo", "OS", "status",
    # The input-data layout of the target (SpecsPy.tex).
    "COMPARTMENT", "COMPARTMENTi", "camelCase",
    # The self-fitting specification (3_HT_Technical_Specification.tex).
    "AuthenticationError", "ConvergenceWarning", "SimulationError", "EstimationLayer",
    "algorithm_kwargs", "calibrated_twin", "compute_gradients", "convergence_criteria",
    "convergence_diagnostics", "evaluate_likelihood", "get_observations",
    "objective_function_history", "optimization_algorithm", "parameter_evolution",
    "parameters_to_calibrate", "posterior_distribution", "private_key", "registry_fingerprint",
    "run_ensemble", "run_frequency_calibration", "run_simulation",
    "run_temporal_bayesian_inference", "target_observations", "validation_metrics",
}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
}


# --------------------------------------------------------------------- the reference


@lru_cache(maxsize=None)
def _kinds() -> dict[str, frozenset[str]]:
    """verb -> the kinds its ladder in ``dispatch.py`` accepts, aliases included."""
    tree = ast.parse((PKG / "ht" / "developer" / "dispatch.py").read_text())
    kinds: dict[str, set[str]] = {}
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef) or fn.name.startswith("_"):
            continue
        found = kinds.setdefault(fn.name, set())
        for node in ast.walk(fn):
            if isinstance(node, ast.Compare) and isinstance(node.comparators[0], ast.Constant):
                left = node.left
                if (isinstance(left, ast.Attribute) and left.attr == "kind") or (
                    isinstance(left, ast.Name) and left.id == "resolved_kind"
                ):
                    found.add(node.comparators[0].value)
            if isinstance(node, ast.Dict) and fn.name == "render" and node.values and all(
                isinstance(v, ast.Constant) and isinstance(v.value, str) for v in node.values
            ):
                found.update(k.value for k in node.keys if isinstance(k, ast.Constant))
    return {verb: frozenset(v) for verb, v in kinds.items() if v}


@lru_cache(maxsize=None)
def _macro_verbs() -> frozenset[str]:
    """The facade's macro-verbs: the methods its lifecycle gate knows."""
    return frozenset(MINIMUM_STATE)


def _public_methods(cls: type) -> set[str]:
    return {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}


@lru_cache(maxsize=None)
def _src_names(root: Path = PKG) -> frozenset[str]:
    """Every name the code under *root* defines: modules, classes, functions,
    arguments, attributes, constants."""
    names: set[str] = {"HydrologicalTwinAlphaSeries"}
    for path in root.rglob("*.py"):
        names.add(path.stem)
        names.update(p.name for p in path.relative_to(root).parents if p.name)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
            elif isinstance(node, ast.alias):
                names.add((node.asname or node.name).split(".")[-1])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[A-Za-z_]\w*", node.value):
                    names.add(node.value)
    return frozenset(names)


@lru_cache(maxsize=None)
def _repo_paths() -> tuple[str, ...]:
    """Every file and directory of the repository, relative to its root."""
    out: list[str] = []

    def walk(directory: Path) -> None:
        for child in directory.iterdir():
            if child.name in _SKIP_DIRS:
                continue
            out.append(child.relative_to(ROOT).as_posix())
            if child.is_dir():
                walk(child)

    walk(ROOT)
    return tuple(out)


@lru_cache(maxsize=None)
def _pixi_tasks() -> frozenset[str]:
    return frozenset(tomllib.loads((ROOT / "pixi.toml").read_text())["tasks"])


# --------------------------------------------------------------------- the documents


# docs/TODO.md is the clean-up backlog: it names code to remove and code
# already removed, so it is the one Markdown document these tests skip.
BACKLOG = ROOT / "docs" / "TODO.md"


def _markdown_docs() -> list[Path]:
    docs = [README, *sorted((ROOT / "docs").glob("*.md")), ROOT / "tests" / "README.md"]
    docs += sorted(PKG.rglob("*.md"))
    docs = [p for p in docs if p != BACKLOG]
    return [p for p in docs if p.is_file()]


def _guide_docs() -> list[Path]:
    if not GUIDE.is_dir():
        return []
    files = [p for p in GUIDE.rglob("*.tex") if not _SKIP_DIRS & set(p.parts)]
    # The Slidev decks; their README and pages/ are Slidev's own template.
    files += [p for p in (GUIDE / "Slidev").rglob("slides.md") if not _SKIP_DIRS & set(p.parts)]
    return sorted(files)


def _all_docs() -> list[Path]:
    return _markdown_docs() + _guide_docs()


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_target(path: Path) -> bool:
    return path.suffix == ".tex" and TARGET_LABEL in path.read_text()


def _strip_latex_comments(text: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in text.splitlines())


def _unlatex(text: str) -> str:
    text = text.replace("\\_", "_").replace("\\#", "#").replace("\\&", "&")
    text = re.sub(r"\\(textbackslash|,|;|!)\s*", "", text)
    return text.replace("$\\rightarrow$", "→").replace("\\ldots", "...")


def _texttt(text: str) -> list[str]:
    """Contents of every ``\\texttt{...}``, with balanced braces."""
    out = []
    for match in re.finditer(r"\\texttt\{", text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out.append(text[match.end() : i - 1])
    return out


def _blocks_and_spans(path: Path) -> tuple[list[tuple[str, str]], list[str], str]:
    """(code blocks as (language, code), inline code spans, prose) of one document."""
    text = path.read_text()
    if path.suffix == ".tex":
        text = _strip_latex_comments(text)
        blocks = [
            ("", textwrap.dedent(m.group(2)))
            for m in re.finditer(r"\\begin\{(verbatim|lstlisting)\}(?:\[[^\]]*\])?(.*?)\\end\{\1\}", text, re.S)
        ]
        prose = re.sub(r"\\begin\{(verbatim|lstlisting)\}.*?\\end\{\1\}", "", text, flags=re.S)
        spans = [_unlatex(s) for s in _texttt(prose)]
        spans += [m.group(2) for m in re.finditer(r"\\verb(.)(.+?)\1", prose)]
        spans = [s for span in spans for s in re.split(r"\s*,\s*", span) if s]
        return blocks, spans, _unlatex(prose)
    blocks = [
        (m.group(1).strip().lower(), m.group(2))
        for m in re.finditer(r"^```([^\n]*)\n(.*?)^```", text, re.S | re.M)
    ]
    prose = re.sub(r"^```[^\n]*\n.*?^```", "", text, flags=re.S | re.M)
    prose = re.sub(r"<!--.*?-->", "", prose, flags=re.S)
    spans = re.findall(r"`([^`\n]+)`", prose)
    return blocks, spans, prose


# --------------------------------------------------------------------- the checks


_PATH_EXT = r"\.(py|toml|md|tex|yml|yaml|json|cgs|txt|pdf|png|gpkg|npy)"


@lru_cache(maxsize=None)
def _dir_names() -> frozenset[str]:
    return frozenset(Path(p).name for p in _repo_paths() if (ROOT / p).is_dir())


def _looks_like_path(token: str) -> bool:
    """A file name with a known extension, a directory (trailing ``/``), or a
    slash path whose first segment is a directory of the repository. Units
    such as ``m3/s`` and host names are not paths."""
    if any(c in token for c in " <>*{}$~=…()\"'") or "..." in token or token.startswith(("/", "http")):
        return False
    if re.match(r"[\w-]+\.(com|org|io|fr|eu|net)/", token) or re.fullmatch(r"\.\w+", token):
        return False
    if re.search(_PATH_EXT + r"(:\d+(-\d+)?)?$", token) or token.endswith("/"):
        return True
    return "/" in token and token.lstrip("./").split("/")[0] in _dir_names() | {"src"}


@lru_cache(maxsize=None)
def _src_file_names() -> frozenset[str]:
    """File names src itself spells out, such as the project file it writes."""
    names = set()
    for path in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[\w.-]+" + _PATH_EXT, node.value):
                    names.add(node.value)
    return frozenset(names)


def _path_exists(token: str) -> bool:
    """A path exists in the repository, or is a file name src spells out.
    ``path::name`` also needs ``name`` to be defined in src."""
    token, _, symbol = token.partition("::")
    if symbol and symbol not in _src_names():
        return False
    token = re.sub(r":\d+(-\d+)?$", "", token).rstrip("/")
    if token in _src_file_names():
        return True
    if (ROOT / token).exists() or (PKG / token).exists() or (GUIDE / token).exists():
        return True
    return any(p == token or p.endswith("/" + token) for p in _repo_paths())


_IDENT = re.compile(r"\.?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:\([^()]*\))?\.?")


def _unknown_names(token: str, allowed: frozenset[str]) -> list[str]:
    match = _IDENT.fullmatch(token.strip())
    if not match:
        return []
    return [part for part in match.group(1).split(".") if part not in allowed]


def _allowed_names(path: Path) -> frozenset[str]:
    """src's names, the external ones, the target's in a target chapter, and
    the tests' own names in the document that describes the tests."""
    extra = set(TARGET_NAMES) if _is_target(path) else set()
    if path.is_relative_to(ROOT / "tests"):
        extra |= _src_names(ROOT / "tests")
    return _src_names() | EXTERNAL_NAMES | extra


_HTAS_OBJECTS = {"twin": HydrologicalTwin, "ht": HydrologicalTwin, "hydro_twin": HydrologicalTwin,
                 "client": HydrologicalTwinClient}
_REQUEST_VERB = {"FetchRequest": "fetch", "MaskRequest": "mask", "TransformRequest": "transform",
                 "RenderRequest": "render", "ExportRequest": "export", "AssembleRequest": "assemble"}


def _kind_problem(verb: str, call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "kind" and isinstance(kw.value, ast.Constant):
            if kw.value.value not in _kinds().get(verb, ()):
                return f"{verb}(kind={kw.value.value!r}) is not a kind of {verb}"
    return None


def _signature_problem(name: str, obj: object, call: ast.Call) -> str | None:
    target = obj.__init__ if inspect.isclass(obj) and not dataclasses.is_dataclass(obj) else obj
    try:
        params = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return None
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return None
    bad = [kw.arg for kw in call.keywords if kw.arg and kw.arg not in params]
    return f"{name}() takes no {', '.join(bad)}" if bad else None


def _python_problems(code: str, imported: dict[str, object], target: bool = False) -> list[str]:
    """Problems in one Python block; ``imported`` carries the document's imports so far."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = node.module if isinstance(node, ast.ImportFrom) else None
            for alias in node.names:
                full = module_name or alias.name
                if not full.startswith("HydrologicalTwinAlphaSeries"):
                    continue
                try:
                    module = importlib.import_module(full)
                except ImportError:
                    problems.append(f"no module {full}")
                    continue
                if module_name is None:
                    imported[(alias.asname or alias.name).split(".")[0]] = module
                elif not hasattr(module, alias.name):
                    problems.append(f"{full} has no {alias.name}")
                else:
                    imported[alias.asname or alias.name] = getattr(module, alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in imported:
            problem = _signature_problem(func.id, imported[func.id], node)
            if func.id in _REQUEST_VERB:
                problem = problem or _kind_problem(_REQUEST_VERB[func.id], node)
            if problem:
                problems.append(problem)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            owner = imported.get(func.value.id) or _HTAS_OBJECTS.get(func.value.id)
            if owner is None:
                continue
            if not hasattr(owner, func.attr):
                if target and func.attr in TARGET_NAMES:
                    continue
                problems.append(f"{func.value.id}.{func.attr}() does not exist")
                continue
            problem = _signature_problem(f"{func.value.id}.{func.attr}", getattr(owner, func.attr), node)
            if func.attr in _kinds():
                problem = problem or _kind_problem(func.attr, node)
            if problem:
                problems.append(problem)
    return problems


def _shell_problems(code: str) -> list[str]:
    problems = []
    for line in code.splitlines():
        line = line.split("#")[0].strip()
        if m := re.match(r"pixi run ([\w-]+)", line):
            if m.group(1) not in _pixi_tasks():
                problems.append(f"no pixi task {m.group(1)!r}")
        if m := re.match(r"(?:pixi run )?htas\s+([\w-]+)(?:\s+([a-z][\w-]*))?", line):
            command, sub = m.group(1), m.group(2)
            if command.startswith("-") or (sub is None and command in COMMANDS):
                continue
            if command not in COMMANDS:
                problems.append(f"no htas command {command!r}")
            elif None not in COMMANDS[command] and sub not in COMMANDS[command]:
                problems.append(f"no htas subcommand {command} {sub}")
    return problems


# --------------------------------------------------------------------- tests


DOCS = _all_docs()
IDS = [_rel(p) for p in DOCS]


@pytest.mark.parametrize("path", DOCS, ids=IDS)
def test_inline_code_names_only_what_exists(path: Path):
    """Every path and Python name in a document's inline code exists."""
    _, spans, _ = _blocks_and_spans(path)
    allowed = _allowed_names(path)
    missing = set()
    target = _is_target(path)
    for span in spans:
        span = span.strip()
        if _looks_like_path(span):
            if not target and not _path_exists(span):
                missing.add(span)
        elif not (ROOT / span).exists():
            missing.update(_unknown_names(span, allowed))
    assert not missing, f"{_rel(path)} names what src does not have: {sorted(missing)}"


@pytest.mark.parametrize("path", DOCS, ids=IDS)
def test_code_blocks_match_src(path: Path):
    """Python blocks import, call and spell kinds as src does; shell lines name real tasks."""
    blocks, _, _ = _blocks_and_spans(path)
    problems: list[str] = []
    imported: dict[str, object] = {}
    for lang, code in blocks:
        if lang in ("", "python", "py"):
            problems += _python_problems(code, imported, _is_target(path))
        if lang in ("", "bash", "sh", "shell", "console"):
            problems += _shell_problems(code)
    assert not problems, f"{_rel(path)}: {problems}"


@pytest.mark.parametrize("path", DOCS, ids=IDS)
def test_kinds_in_prose_exist(path: Path):
    """Every ``verb(kind="x")`` and ``kind="x"`` in prose is a kind src dispatches."""
    _, spans, prose = _blocks_and_spans(path)
    text = prose + "\n" + "\n".join(spans)
    every_kind = set().union(*_kinds().values())
    problems = []
    for m in re.finditer(r"(?:\b(\w+)\()?kind\s*=\s*[\"'](\w+)[\"']", text):
        verb, kind = m.group(1), m.group(2)
        known = _kinds().get(verb, every_kind) if verb in _kinds() else every_kind
        if kind not in known:
            problems.append(f"{verb or ''}(kind={kind!r})")
    assert not problems, f"{_rel(path)} names kinds src does not dispatch: {problems}"


@pytest.mark.parametrize("path", DOCS, ids=IDS)
def test_macro_verb_counts_are_true(path: Path):
    """A number of macro-verbs written in prose is the number the facade has."""
    _, _, prose = _blocks_and_spans(path)
    prose = re.sub(r"\s+", " ", prose.lower())
    wanted = len(_macro_verbs())
    wrong = []
    pattern = r"\b(\d+|" + "|".join(_NUMBER_WORDS) + r")[ -](?:canonical |macro[- ])?(?:macro[- ])?(?:verbs?|methods?|méthodes?|entrypoints?)\b"
    for m in re.finditer(pattern, prose):
        if "macro" not in m.group(0) and "canonical" not in m.group(0) and "-method" not in m.group(0):
            continue
        number = int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS[m.group(1)]
        if number != wanted:
            wrong.append(m.group(0))
    wrong += [m.group(0) for m in re.finditer(r"macro[- ]methods? \(≤ ?(\d+)\)", prose) if int(m.group(1)) < wanted]
    assert not wrong, f"{_rel(path)} counts {wrong}; the facade has {wanted} macro-verbs"


@pytest.mark.parametrize("path", [p for p in DOCS if p.suffix == ".md"], ids=lambda p: _rel(p))
def test_relative_links_resolve(path: Path):
    text = re.sub(r"^```.*?^```", "", path.read_text(), flags=re.S | re.M)
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if not (path.parent / target.split("#")[0]).exists():
            broken.append(target)
    assert not broken, f"{_rel(path)} has broken links: {broken}"


def test_api_capabilities_names_every_client_method_verb_and_kind():
    """docs/api_capabilities.md lists the whole public surface src has."""
    text = (ROOT / "docs" / "api_capabilities.md").read_text()
    named = set(re.findall(r"`(\w+)", text))
    missing = (_public_methods(HydrologicalTwinClient) | _macro_verbs()) - named
    for verb, kinds in _kinds().items():
        section = re.search(rf"^### `{verb}\(.*?(?=^#{{2,3}} |\Z)", text, re.S | re.M)
        body = section.group(0) if section else ""
        missing |= {f"{verb}:{k}" for k in kinds if f"`{k}`" not in body}
    assert not missing, f"docs/api_capabilities.md does not document: {sorted(missing)}"


def test_readme_is_a_short_user_front_page():
    """The README is user-facing: at most 250 lines, and no method or command table."""
    lines = README.read_text().splitlines()
    assert len(lines) <= README_MAX_LINES, f"README.md has {len(lines)} lines (max {README_MAX_LINES})"
    surface = _public_methods(HydrologicalTwinClient) | _macro_verbs() | set(COMMANDS)
    listed = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
        if cells and (m := re.fullmatch(r"`(?:htas )?(\w+)[^`]*`", cells[0])) and m.group(1) in surface:
            listed.append(cells[0])
    assert not listed, f"README.md lists methods or commands in a table: {listed}"


def test_target_chapters_are_labelled_where_defined():
    """\\htastarget is defined in every LaTeX document that uses it."""
    if not GUIDE.is_dir():
        pytest.skip("docs/hydrological_twin is not checked out")
    users = [p for p in GUIDE.rglob("*.tex") if TARGET_LABEL + "\n" in p.read_text() or TARGET_LABEL + " " in p.read_text()]
    defined = "\\newcommand{" + TARGET_LABEL + "}"
    shortcuts = (GUIDE / "Setup" / "Shortcuts.tex").read_text()
    for path in users:
        standalone = "\\documentclass" in path.read_text()
        source = path.read_text() if standalone else shortcuts
        assert defined in source, f"{_rel(path)} uses {TARGET_LABEL} but its document does not define it"
