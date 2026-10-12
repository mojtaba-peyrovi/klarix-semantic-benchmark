"""Find this project's model in a running Power BI Desktop and run DAX against it.

Desktop starts a private Analysis Services engine (msmdsrv) per open project, on a random
localhost port that it records in `msmdsrv.port.txt` inside the project's workspace folder.
There is nothing in the engine's database name that identifies a project (it is a GUID), so
an instance is recognised by its tables. If none or more than one instance matches we raise:
this module never guesses which model to talk to.

ADOMD.NET is loaded through pythonnet on the .NET Framework runtime (ships with Windows). The
DLL is downloaded by `setup_adomd.py` into a gitignored folder.
"""

from __future__ import annotations

import datetime as dt
import glob
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
ADOMD_DLL = PROJECT_DIR / ".adomd" / "Microsoft.AnalysisServices.AdomdClient.dll"
PBIP_RELATIVE = "project3-powerbi-tmdl/pbip/KlarixApparel.pbip"

# Store install keeps workspaces under the user profile, the installer build under LocalAppData
# (the second is the documented location; only the Store layout was verified on this machine).
_WORKSPACES = r"Microsoft\Power BI Desktop*\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt"
PORT_FILE_PATTERNS = (rf"%USERPROFILE%\{_WORKSPACES}", rf"%LOCALAPPDATA%\{_WORKSPACES}")


class DesktopError(RuntimeError):
    """A readable problem finding or reaching the model (the message is meant for the user)."""


@dataclass(frozen=True)
class Instance:
    port: int
    catalog: str
    tables: frozenset[str]


_adomd: tuple | None = None


def _load_adomd() -> tuple:
    """Load ADOMD.NET once per process; returns (AdomdConnection, AdomdCommand)."""
    global _adomd
    if _adomd is not None:
        return _adomd
    if os.name != "nt":
        raise DesktopError("Power BI Desktop only runs on Windows.")
    if not ADOMD_DLL.exists():
        raise DesktopError("ADOMD.NET is not installed; run `make p3-setup` first.")
    from pythonnet import load

    load("netfx")
    import clr

    clr.AddReference(str(ADOMD_DLL))
    from Microsoft.AnalysisServices.AdomdClient import AdomdCommand, AdomdConnection

    _adomd = (AdomdConnection, AdomdCommand)
    return _adomd


def candidate_ports() -> list[int]:
    """Ports recorded by every Desktop workspace on this machine (may include stale files)."""
    ports: list[int] = []
    for pattern in PORT_FILE_PATTERNS:
        for path in sorted(glob.glob(os.path.expandvars(pattern))):
            raw = Path(path).read_bytes()
            text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode()
            text = text.strip()
            if not text.isdigit():
                # the engine writes UTF-16 without a BOM, which decodes as NULs-interleaved text
                text = raw.decode("utf-16-le", errors="ignore").strip()
            if text.isdigit() and int(text) not in ports:
                ports.append(int(text))
    return ports


def _python_value(value: object) -> object:
    if value is None:
        return None
    if type(value).__name__ == "DateTime":
        return dt.datetime(
            value.Year, value.Month, value.Day, value.Hour, value.Minute, value.Second
        )
    return value


def run_dax(connection, text: str) -> tuple[list[str], list[list]]:
    """Run a DAX query (or a DMV query) and return (column names, rows)."""
    _, command_type = _load_adomd()
    reader = command_type(text, connection).ExecuteReader()
    try:
        names = [reader.GetName(i) for i in range(reader.FieldCount)]
        rows = []
        while reader.Read():
            rows.append(
                [
                    None if reader.IsDBNull(i) else _python_value(reader.GetValue(i))
                    for i in range(reader.FieldCount)
                ]
            )
    finally:
        reader.Close()
    return names, rows


def open_connection(port: int, catalog: str | None = None):
    connection_type, _ = _load_adomd()
    text = f"Data Source=localhost:{port}"
    if catalog:
        text += f";Initial Catalog={catalog}"
    connection = connection_type(text)
    connection.Open()
    return connection


def _describe(port: int) -> Instance | None:
    """Table names of the instance on `port`, or None if nothing answers (stale port file)."""
    try:
        connection = open_connection(port)
    except Exception:  # noqa: BLE001 - a dead or foreign port is simply not a candidate
        return None
    try:
        _, rows = run_dax(connection, "SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS")
        if len(rows) != 1:
            return None
        catalog = rows[0][0]
    finally:
        connection.Close()
    connection = open_connection(port, catalog)
    try:
        _, table_rows = run_dax(connection, 'EVALUATE SELECTCOLUMNS(INFO.TABLES(), "n", [Name])')
    finally:
        connection.Close()
    return Instance(port, catalog, frozenset(r[0] for r in table_rows))


def find_instance(expected_tables: set[str] | frozenset[str]) -> Instance:
    """The one running Desktop instance that holds all of `expected_tables`."""
    ports = candidate_ports()
    open_help = f"Open {PBIP_RELATIVE} in Power BI Desktop (and refresh it)."
    if not ports:
        raise DesktopError(f"Power BI Desktop is not open. {open_help}")
    described = [d for d in map(_describe, ports) if d is not None]
    matches = [d for d in described if expected_tables <= d.tables]
    if not matches:
        others = ", ".join(f"port {d.port} ({len(d.tables)} tables)" for d in described) or "none"
        raise DesktopError(
            "Power BI Desktop is open but none of its models is this project's (or the open "
            f"window predates a model change: close and reopen it). {open_help} "
            f"Instances found: {others}."
        )
    if len(matches) > 1:
        ports_text = ", ".join(str(d.port) for d in matches)
        raise DesktopError(
            f"More than one open Desktop window holds this model (ports {ports_text}); "
            "close all but one so the backend does not guess."
        )
    return matches[0]
