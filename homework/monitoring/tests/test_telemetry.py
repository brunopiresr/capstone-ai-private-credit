import json
import subprocess
import sys
from pathlib import Path


def test_modes_share_web_identity_with_separate_interaction_traces(data_root, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("telemetry_probe.py")),
            str(data_root),
            str(tmp_path / "runtime"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence["interactions"] == 5 and evidence["isolated_reset"]
