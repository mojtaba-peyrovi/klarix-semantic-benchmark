"""Download Microsoft's ADOMD.NET client from NuGet into a gitignored folder.

The DLL is Microsoft's, so it is never committed. `desktop_connection.py` loads it through
pythonnet (.NET Framework runtime, which ships with Windows). The package version and its
SHA-256 are pinned; a mismatch aborts before anything is extracted.
"""

from __future__ import annotations

import hashlib
import io
import urllib.request
import zipfile

import typer

from shared.settings import REPO_ROOT

VERSION = "19.117.0"
PACKAGE = "Microsoft.AnalysisServices.AdomdClient"
URL = f"https://www.nuget.org/api/v2/package/{PACKAGE}/{VERSION}"
SHA256 = "94b2455d57447c720e106c7d7d78e3d71ffdb6ad1f44226d5121f3ce9a70b569"
DLL_IN_PACKAGE = "lib/net472/Microsoft.AnalysisServices.AdomdClient.dll"
TARGET_DIR = REPO_ROOT / "project3-powerbi-tmdl" / ".adomd"
DLL_PATH = TARGET_DIR / "Microsoft.AnalysisServices.AdomdClient.dll"


def main(force: bool = typer.Option(False, help="Download again even if the DLL exists.")) -> None:
    if DLL_PATH.exists() and not force:
        print(f"{DLL_PATH.relative_to(REPO_ROOT)} already present")
        return
    print(f"Downloading {PACKAGE} {VERSION} from NuGet ...")
    with urllib.request.urlopen(URL, timeout=60) as response:  # noqa: S310 - fixed https URL
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise SystemExit(
            f"SHA-256 mismatch for {PACKAGE} {VERSION}: got {digest}, expected {SHA256}"
        )
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        DLL_PATH.write_bytes(package.read(DLL_IN_PACKAGE))
    print(f"Wrote {DLL_PATH.relative_to(REPO_ROOT)} ({DLL_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    typer.run(main)
