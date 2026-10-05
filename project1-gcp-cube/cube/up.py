"""`make cube-up`: start the local Cube Core container (docker-compose.yml) and wait
for it to answer /readyz.

docker-compose.yml's env vars (GCP_PROJECT_ID, BQ_LOCATION, CUBEJS_API_SECRET,
CUBE_SA_KEY_PATH) are substituted from the calling process's environment, not from a
.env file in this directory -- so this script loads settings/.env the same way the
rest of the repo does (shared.settings) and passes them through to `docker compose`
explicitly, instead of duplicating them in a second .env file here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from rich.console import Console

from shared.settings import load_settings

console = Console()

CUBE_DIR = Path(__file__).resolve().parent
READY_URL = "http://localhost:4000/readyz"
READY_TIMEOUT_S = 90


def main() -> None:
    s = load_settings()
    missing = [
        name
        for name in ("GCP_PROJECT_ID", "CUBEJS_API_SECRET", "CUBE_SA_KEY_PATH")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f".env is missing: {', '.join(missing)}")

    env = os.environ.copy()
    env["BQ_LOCATION"] = s.gcp.bq_location
    # Docker Desktop's bind-mount source wants forward slashes even on Windows.
    env["CUBE_SA_KEY_PATH"] = env["CUBE_SA_KEY_PATH"].replace("\\", "/")

    key_path = Path(env["CUBE_SA_KEY_PATH"])
    if not key_path.exists():
        raise SystemExit(f"CUBE_SA_KEY_PATH does not exist: {key_path}")

    subprocess.run(
        ["docker", "compose", "-f", str(CUBE_DIR / "docker-compose.yml"), "up", "-d"],
        cwd=CUBE_DIR,
        env=env,
        check=True,
    )

    console.print("Waiting for Cube to become ready...")
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(READY_URL, timeout=5)
            if resp.status_code == 200:
                console.print("[green]Cube is ready at http://localhost:4000[/]")
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit(
        f"Cube did not become ready within {READY_TIMEOUT_S}s; check `docker compose logs`."
    )


if __name__ == "__main__":
    sys.exit(main())
