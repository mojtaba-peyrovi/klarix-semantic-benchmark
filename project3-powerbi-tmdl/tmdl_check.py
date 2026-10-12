"""A small TMDL reader for the static tests. It is not a general TMDL parser.

It understands the subset this project writes and Power BI Desktop writes back: objects
declared as `kind name [= expression]`, `key: value` properties, bare boolean flags, `///`
descriptions, multi-line expressions (including triple-backtick blocks) and `ref` lines.
Anything outside that subset is kept as a generic node rather than interpreted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent / "pbip" / "KlarixApparel.SemanticModel" / "definition"

KINDS = {
    "table", "column", "measure", "partition", "relationship", "expression", "model", "database",
    "annotation", "ref", "hierarchy", "level", "role", "culture", "perspective", "calculationGroup",
}  # fmt: skip
_PROPERTY = re.compile(r"^(\w+):\s*(.*)$")
_REFERENCE = re.compile(r"^(?:'((?:[^']|'')+)'|([^.']+))\.(?:'((?:[^']|'')+)'|(.+))$")


@dataclass
class Node:
    kind: str
    name: str
    expression: str | None = None
    description: str | None = None
    props: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    children: list[Node] = field(default_factory=list)


@dataclass(frozen=True)
class Relationship:
    id: str
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    props: dict[str, str]


def _unquote_name(text: str) -> str:
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1].replace("''", "'")
    return text


def _split_header(content: str) -> tuple[str, str, str | None]:
    """`column 'My col' = expr` -> ('column', 'My col', 'expr' or '' when it continues below)."""
    kind, _, rest = content.partition(" ")
    rest = rest.strip()
    if rest.startswith("'"):
        end = 1
        while True:
            end = rest.index("'", end)
            if rest[end + 1 : end + 2] == "'":  # doubled quote inside the name
                end += 2
                continue
            break
        name, after = rest[: end + 1], rest[end + 1 :].strip()
    else:
        match = re.match(r"([^\s=]+)\s*(.*)$", rest)
        name, after = (match.group(1), match.group(2)) if match else (rest, "")
    expression = after[1:].strip() if after.startswith("=") else None
    return kind, _unquote_name(name), expression


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip("\t"))


def parse(text: str) -> list[Node]:
    """Parse one TMDL document into its top-level nodes."""
    lines = [line.rstrip("\r") for line in text.split("\n")]
    root = Node("root", "")
    stack: list[tuple[int, Node]] = [(-1, root)]
    description: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        content = line.strip("\t").strip()
        if not content:
            continue
        if content.startswith("///"):
            description.append(content[3:].strip())
            continue
        level = _indent(line)
        while stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        prop = _PROPERTY.match(content)
        first = content.split(" ", 1)[0]
        is_prop_with_expr = re.match(r"^(\w+)\s*=", content) and first not in KINDS
        if prop or is_prop_with_expr:
            key = prop.group(1) if prop else re.match(r"^(\w+)", content).group(1)
            value = prop.group(2) if prop else content.split("=", 1)[1].strip()
            if not prop:  # `source = ...`: an expression property
                value, i = _read_expression(lines, i, level, value)
            parent.props[key] = value.strip('"') if prop and value.startswith('"') else value
            continue
        if first not in KINDS:
            parent.flags.add(content)
            continue
        kind, name, expression = _split_header(content)
        if expression is not None:
            expression, i = _read_expression(lines, i, level, expression)
        node = Node(kind, name, expression, " ".join(description) or None)
        description = []
        parent.children.append(node)
        stack.append((level, node))
    return root.children


def _read_expression(lines: list[str], i: int, level: int, first: str) -> tuple[str, int]:
    """Collect a (possibly multi-line) expression that starts after an `=`."""
    if first == "```":
        body = []
        while i < len(lines) and lines[i].strip("\t").strip() != "```":
            body.append(lines[i].rstrip("\r"))
            i += 1
        return "\n".join(body).strip(), i + 1
    if first:
        return first, i
    body = []
    while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > level + 1):
        body.append(lines[i].rstrip("\r"))
        i += 1
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body).strip(), i


@dataclass(frozen=True)
class Column:
    table: str
    name: str
    data_type: str
    hidden: bool
    summarize_by: str | None
    source_column: str | None
    is_key: bool
    description: str | None
    format_string: str | None


@dataclass(frozen=True)
class Measure:
    table: str
    name: str
    expression: str
    hidden: bool
    description: str | None
    format_string: str | None
    display_folder: str | None


@dataclass
class Table:
    name: str
    node: Node
    columns: dict[str, Column]
    measures: dict[str, Measure]

    @property
    def hidden(self) -> bool:
        return "isHidden" in self.node.flags

    @property
    def data_category(self) -> str | None:
        return self.node.props.get("dataCategory")


@dataclass
class Model:
    tables: dict[str, Table]
    relationships: list[Relationship]
    expressions: dict[str, Node]
    flags: set[str]
    annotations: dict[str, str]


def _reference(text: str) -> tuple[str, str]:
    match = _REFERENCE.match(text)
    if not match:
        raise ValueError(f"cannot read column reference {text!r}")
    table = (match.group(1) or match.group(2)).replace("''", "'")
    column = (match.group(3) or match.group(4)).replace("''", "'")
    return table, column


def _table(node: Node) -> Table:
    columns, measures = {}, {}
    for child in node.children:
        if child.kind == "column":
            columns[child.name] = Column(
                node.name, child.name, child.props.get("dataType", ""), "isHidden" in child.flags,
                child.props.get("summarizeBy"), child.props.get("sourceColumn"),
                "isKey" in child.flags, child.description, child.props.get("formatString"),
            )  # fmt: skip
        elif child.kind == "measure":
            measures[child.name] = Measure(
                node.name, child.name, child.expression or "", "isHidden" in child.flags,
                child.description, child.props.get("formatString"),
                child.props.get("displayFolder"),
            )  # fmt: skip
    return Table(node.name, node, columns, measures)


def load_model(directory: Path = MODEL_DIR) -> Model:
    model = Model({}, [], {}, set(), {})
    files = sorted(directory.glob("*.tmdl")) + sorted((directory / "tables").glob("*.tmdl"))
    for path in files:
        for node in parse(path.read_text(encoding="utf-8")):
            if node.kind == "table":
                model.tables[node.name] = _table(node)
            elif node.kind == "relationship":
                from_table, from_column = _reference(node.props["fromColumn"])
                to_table, to_column = _reference(node.props["toColumn"])
                model.relationships.append(
                    Relationship(
                        node.name, from_table, from_column, to_table, to_column, node.props
                    )
                )
            elif node.kind == "expression":
                model.expressions[node.name] = node
            elif node.kind == "model":
                model.flags |= node.flags
            elif node.kind == "annotation":
                model.annotations[node.name] = node.expression or ""
    return model


def table_names(directory: Path = MODEL_DIR) -> list[str]:
    return sorted(load_model(directory).tables)
