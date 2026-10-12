"""Point the semantic model's DataFolder parameter at this checkout's data/powerbi folder.

The committed expressions.tmdl keeps the placeholder `__DATA_FOLDER__` so no machine-specific
path reaches git. Run this locally after `make p3-export`; run it with `--reset` before
committing if Desktop has not rewritten the file (Desktop keeps the path you set).
"""

from __future__ import annotations

import re

import typer

from shared.settings import REPO_ROOT

EXPRESSIONS_PATH = (
    REPO_ROOT
    / "project3-powerbi-tmdl"
    / "pbip"
    / "KlarixApparel.SemanticModel"
    / "definition"
    / "expressions.tmdl"
)
PLACEHOLDER = "__DATA_FOLDER__"
# Matches the quoted value of `expression DataFolder = "..."`, whatever it currently holds.
VALUE = re.compile(r'(expression DataFolder = ")[^"\r\n]*(")')


def main(reset: bool = typer.Option(False, help="Restore the committed placeholder.")) -> None:
    if not EXPRESSIONS_PATH.exists():
        raise SystemExit(f"{EXPRESSIONS_PATH} not found")
    # Newline-preserving read/write: Desktop writes CRLF and we must not change the endings.
    with EXPRESSIONS_PATH.open(encoding="utf-8", newline="") as handle:
        text = handle.read()
    if not VALUE.search(text):
        raise SystemExit('`expression DataFolder = "..."` not found in expressions.tmdl')
    value = PLACEHOLDER if reset else str((REPO_ROOT / "data" / "powerbi").resolve())
    # M strings only need " doubled; Windows backslashes are literal.
    updated = VALUE.sub(lambda m: f"{m.group(1)}{value.replace('"', '""')}{m.group(2)}", text)
    with EXPRESSIONS_PATH.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    print(f"DataFolder = {value}")
    if not reset:
        print("Local path set. Run this script with --reset before committing.")


if __name__ == "__main__":
    typer.run(main)
