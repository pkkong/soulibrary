"""
Run CSV partial ingest and post-ingest quality stages in sequence.

Usage:
  python scripts/run_ingest_quality_pipeline.py --csv-only gangdong_subs,gwangjin_subs
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run partial CSV ingest, then Stage1/Stage2/Stage3 queue build."
    )
    parser.add_argument(
        "--csv-only",
        required=True,
        help="Comma-separated library codes or CSV basenames",
    )
    return parser.parse_args()


def _tail(text, limit=12000):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def _extract_json_payload(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _run_step(step, env):
    cmd = [sys.executable] + list(step["command"])
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "key": step["key"],
        "label": step["label"],
        "command": " ".join(cmd),
        "returncode": int(result.returncode),
        "success": result.returncode == 0,
        "result_json": _extract_json_payload(result.stdout) or _extract_json_payload(result.stderr),
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }


def main() -> int:
    args = parse_args()

    env = os.environ.copy()
    csv_only = str(args.csv_only or "").strip()
    if not csv_only:
        raise SystemExit("--csv-only is required")

    steps = [
        {
            "key": "partial_ingest",
            "label": "CSV 적재 (부분 반영)",
            "command": ["scripts/load_csv_partial.py", "--csv-only", csv_only],
        },
        {
            "key": "stage1_apply",
            "label": "Stage1 적용",
            "command": [
                "scripts/stage1_apply_exact_dedupe.py",
                "--apply",
                "--scope",
                "all",
                "--dedupe-holdings",
                "--add-unique",
            ],
        },
        {
            "key": "stage2_apply",
            "label": "Stage2 적용",
            "command": [
                "scripts/stage2_apply_identifier_merge.py",
                "--apply",
                "--dedupe-holdings",
            ],
        },
        {
            "key": "stage3_build_queue",
            "label": "Stage3 후보 생성",
            "command": ["scripts/stage3_build_review_queue.py"],
        },
    ]

    payload = {
        "measured_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_target": {
            "host": env.get("DB_HOST", "localhost"),
            "port": env.get("DB_PORT", "5432"),
            "name": env.get("DB_NAME", "postgres"),
        },
        "csv_only": csv_only,
        "steps": [],
        "success": False,
        "failed_step": None,
    }

    exit_code = 0
    for step in steps:
        step_result = _run_step(step, env)
        payload["steps"].append(step_result)
        if not step_result["success"]:
            payload["failed_step"] = step["key"]
            exit_code = step_result["returncode"] or 1
            break

    payload["completed_steps"] = [
        step["key"] for step in payload["steps"] if step.get("success")
    ]
    payload["success"] = payload["failed_step"] is None

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
