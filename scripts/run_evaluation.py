"""Run offline Evidently judges in their compatible, isolated Python environment."""

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("Install uv to run the isolated Evidently judges environment.", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    return subprocess.call(
        [
            uv,
            "run",
            "--project",
            str(root / "tools/llm_judges"),
            "--locked",
            "python",
            "-m",
            "credit_monitoring_judges",
            *sys.argv[1:],
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
