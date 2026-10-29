"""Verify SDK span names and actual parent IDs in a fresh, offline process."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("capture_content", ["true", "false"])
def test_feedback_is_under_its_completed_request(tmp_path, capture_content):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("evaluation_telemetry_probe.py")),
            str(tmp_path),
            capture_content,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {
        "requests": 4,
        "feedback": 3,
        "parenting_verified": True,
    }
