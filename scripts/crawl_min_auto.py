import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional


DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Paths:
    root: Path
    web: Path
    data: Path


def _paths() -> Paths:
    root = Path(__file__).resolve().parents[1]
    return Paths(root=root, web=root / "web", data=root / "data")


def _ensure_import_path(paths: Paths) -> None:
    if str(paths.web) not in sys.path:
        sys.path.insert(0, str(paths.web))
    if str(paths.root) not in sys.path:
        sys.path.insert(0, str(paths.root))


def _now() -> datetime:
    return datetime.now()


def _dt_str(dt: datetime) -> str:
    return dt.strftime(DATETIME_FMT)


def _parse_dt(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime(text, DATETIME_FMT)
    except Exception:
        return None


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            return sum(1 for _ in reader)
    except Exception:
        return 0


def _load_libraries(paths: Paths):
    _ensure_import_path(paths)
    from config import LIBRARIES  # pylint: disable=import-outside-toplevel

    return LIBRARIES


def _scan_cache_mode(paths: Paths, libraries: dict, remote_in: Path) -> Dict[str, dict]:
    cached = _read_json(remote_in, default={})
    results = {}
    for code, cfg in libraries.items():
        db_path = Path(cfg.get("db_file", ""))
        if not db_path.is_absolute():
            db_path = paths.root / db_path
        local_count = _count_csv_rows(db_path)
        remote_count = int((cached.get(code) or {}).get("remote_count") or -1)
        checked_at = (cached.get(code) or {}).get("checked_at") or None
        diff = abs(remote_count - local_count) if remote_count >= 0 else None
        results[code] = {
            "code": code,
            "name": cfg.get("name", code),
            "local_count": local_count,
            "remote_count": remote_count,
            "diff": diff,
            "checked_at": checked_at,
            "source": "cache",
        }
    return results


def _scan_live_mode(paths: Paths, libraries: dict) -> Dict[str, dict]:
    _ensure_import_path(paths)
    from crawler_manager import check_library_update  # pylint: disable=import-outside-toplevel

    results = {}
    for code, cfg in libraries.items():
        local_count, remote_count = check_library_update(code)
        diff = abs(remote_count - local_count) if remote_count >= 0 else None
        results[code] = {
            "code": code,
            "name": cfg.get("name", code),
            "local_count": int(local_count),
            "remote_count": int(remote_count),
            "diff": diff,
            "checked_at": _dt_str(_now()),
            "source": "live",
        }
    return results


def cmd_scan(args) -> int:
    paths = _paths()
    libraries = _load_libraries(paths)

    remote_in = (paths.root / args.remote_in).resolve() if not Path(args.remote_in).is_absolute() else Path(args.remote_in)
    remote_out = (paths.root / args.remote_out).resolve() if not Path(args.remote_out).is_absolute() else Path(args.remote_out)
    candidates_out = (paths.root / args.candidates_out).resolve() if not Path(args.candidates_out).is_absolute() else Path(args.candidates_out)

    if args.mode == "live":
        rows = _scan_live_mode(paths, libraries)
    else:
        rows = _scan_cache_mode(paths, libraries, remote_in=remote_in)

    threshold = int(args.threshold)
    generated_at = _dt_str(_now())
    remote_map = {}
    all_rows: List[dict] = []
    candidates: List[dict] = []
    for code in sorted(rows.keys()):
        row = rows[code]
        diff = row.get("diff")
        recommend = bool(diff is not None and diff >= threshold)
        remote_map[code] = {
            "remote_count": row.get("remote_count"),
            "local_count": row.get("local_count"),
            "difference": diff,
            "recommend_update": recommend,
            "checked_at": row.get("checked_at") or generated_at,
            "source": row.get("source"),
        }
        payload = {
            "code": code,
            "name": row.get("name"),
            "local_count": row.get("local_count"),
            "remote_count": row.get("remote_count"),
            "diff": diff,
            "recommend_update": recommend,
        }
        all_rows.append(payload)
        if recommend:
            candidates.append(payload)

    report = {
        "generated_at": generated_at,
        "mode": args.mode,
        "threshold": threshold,
        "candidate_count": len(candidates),
        "candidates": sorted(candidates, key=lambda x: x["diff"], reverse=True),
        "all": all_rows,
    }

    _write_json(remote_out, remote_map)
    _write_json(candidates_out, report)

    print(f"[scan] mode={args.mode} threshold={threshold} candidates={len(candidates)}")
    print(f"[scan] remote_out={remote_out}")
    print(f"[scan] candidates_out={candidates_out}")
    for c in report["candidates"][:20]:
        print(
            f"  - {c['code']}: diff={c['diff']} "
            f"(local={c['local_count']}, remote={c['remote_count']})"
        )
    return 0


def _next_night_run(night_time: str, now: datetime) -> datetime:
    try:
        hh, mm = night_time.split(":")
        hour = int(hh)
        minute = int(mm)
    except Exception as exc:
        raise ValueError("night_time must be HH:MM") from exc
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _queue_defaults() -> dict:
    return {"version": 1, "updated_at": None, "items": []}


def _load_queue(path: Path) -> dict:
    data = _read_json(path, default=_queue_defaults())
    if not isinstance(data, dict):
        return _queue_defaults()
    if "items" not in data or not isinstance(data["items"], list):
        data["items"] = []
    if "version" not in data:
        data["version"] = 1
    return data


def _save_queue(path: Path, queue: dict) -> None:
    queue["updated_at"] = _dt_str(_now())
    _write_json(path, queue)


def _has_pending_for_lib(queue: dict, lib_code: str) -> bool:
    for item in queue.get("items", []):
        if item.get("lib_code") != lib_code:
            continue
        if item.get("status") in {"pending", "running"}:
            return True
    return False


def _build_queue_item(lib_code: str, lib_name: str, action: str, run_at: datetime, max_retries: int, source: str) -> dict:
    now = _now()
    item_id = f"{now.strftime('%Y%m%d%H%M%S')}_{lib_code}"
    return {
        "id": item_id,
        "lib_code": lib_code,
        "library_name": lib_name,
        "action": action,
        "run_at": _dt_str(run_at),
        "status": "pending",
        "tries": 0,
        "max_retries": int(max_retries),
        "created_at": _dt_str(now),
        "updated_at": _dt_str(now),
        "last_error": "",
        "source": source,
    }


def _resolve_path(root: Path, text: str) -> Path:
    p = Path(text)
    return p if p.is_absolute() else (root / p).resolve()


def cmd_queue_add(args) -> int:
    paths = _paths()
    libraries = _load_libraries(paths)
    queue_path = _resolve_path(paths.root, args.queue_file)
    queue = _load_queue(queue_path)
    now = _now()

    codes = list(dict.fromkeys(args.lib))
    added = 0
    skipped = 0
    for code in codes:
        if code not in libraries:
            print(f"[queue] skip unknown lib: {code}")
            skipped += 1
            continue
        if args.action == "skip":
            print(f"[queue] skip by action=skip: {code}")
            skipped += 1
            continue
        if _has_pending_for_lib(queue, code):
            print(f"[queue] already pending/running: {code}")
            skipped += 1
            continue

        if args.action == "immediate":
            run_at = now
        else:
            run_at = _next_night_run(args.night_time, now=now)

        item = _build_queue_item(
            lib_code=code,
            lib_name=libraries[code].get("name", code),
            action=args.action,
            run_at=run_at,
            max_retries=args.max_retries,
            source="manual",
        )
        queue["items"].append(item)
        added += 1
        print(f"[queue] added {code} action={args.action} run_at={item['run_at']}")

    _save_queue(queue_path, queue)
    print(f"[queue] file={queue_path} added={added} skipped={skipped}")
    return 0


def cmd_queue_from_candidates(args) -> int:
    paths = _paths()
    libraries = _load_libraries(paths)
    candidates_path = _resolve_path(paths.root, args.candidates_file)
    queue_path = _resolve_path(paths.root, args.queue_file)
    report = _read_json(candidates_path, default={})
    candidates = report.get("candidates") or []
    queue = _load_queue(queue_path)
    now = _now()

    if args.limit > 0:
        candidates = candidates[: args.limit]

    added = 0
    skipped = 0
    for c in candidates:
        code = c.get("code")
        if not code or code not in libraries:
            skipped += 1
            continue
        if args.action == "skip":
            skipped += 1
            continue
        if _has_pending_for_lib(queue, code):
            skipped += 1
            continue
        run_at = now if args.action == "immediate" else _next_night_run(args.night_time, now)
        item = _build_queue_item(
            lib_code=code,
            lib_name=libraries[code].get("name", code),
            action=args.action,
            run_at=run_at,
            max_retries=args.max_retries,
            source="candidates",
        )
        queue["items"].append(item)
        added += 1
        print(f"[queue-from-candidates] added {code} run_at={item['run_at']}")

    _save_queue(queue_path, queue)
    print(f"[queue-from-candidates] file={queue_path} added={added} skipped={skipped}")
    return 0


def cmd_queue_interactive(args) -> int:
    paths = _paths()
    libraries = _load_libraries(paths)
    candidates_path = _resolve_path(paths.root, args.candidates_file)
    queue_path = _resolve_path(paths.root, args.queue_file)
    report = _read_json(candidates_path, default={})
    candidates = report.get("candidates") or []
    queue = _load_queue(queue_path)
    now = _now()
    added = 0
    skipped = 0

    print("[interactive] choose per library: [i]=immediate [n]=night [s]=skip (default s)")
    for c in candidates:
        code = c.get("code")
        if not code or code not in libraries:
            skipped += 1
            continue
        if _has_pending_for_lib(queue, code):
            print(f"  {code}: already pending/running, skip")
            skipped += 1
            continue

        diff = c.get("diff")
        prompt = f"  {code} diff={diff} -> "
        choice = (input(prompt).strip().lower() or "s")
        if choice not in {"i", "n", "s"}:
            choice = "s"

        if choice == "s":
            skipped += 1
            continue
        action = "immediate" if choice == "i" else "night"
        run_at = now if action == "immediate" else _next_night_run(args.night_time, now)
        item = _build_queue_item(
            lib_code=code,
            lib_name=libraries[code].get("name", code),
            action=action,
            run_at=run_at,
            max_retries=args.max_retries,
            source="interactive",
        )
        queue["items"].append(item)
        added += 1
        print(f"    added {code} action={action} run_at={item['run_at']}")

    _save_queue(queue_path, queue)
    print(f"[interactive] file={queue_path} added={added} skipped={skipped}")
    return 0


def cmd_show_queue(args) -> int:
    paths = _paths()
    queue_path = _resolve_path(paths.root, args.queue_file)
    queue = _load_queue(queue_path)
    items = sorted(queue.get("items", []), key=lambda x: (x.get("status") != "pending", x.get("run_at", "")))
    print(f"[show-queue] file={queue_path} items={len(items)}")
    for item in items:
        print(
            f"  - {item.get('id')} {item.get('lib_code')} status={item.get('status')} "
            f"run_at={item.get('run_at')} tries={item.get('tries')}/{item.get('max_retries')}"
        )
    return 0


def _execute_crawl(libraries: dict, paths: Paths, lib_code: str, dry_run: bool) -> Optional[str]:
    cfg = libraries.get(lib_code)
    if not cfg:
        return f"unknown lib_code: {lib_code}"
    cmd = cfg.get("cmd")
    if not isinstance(cmd, list) or not cmd:
        return f"invalid cmd config for {lib_code}"
    if dry_run:
        print(f"[run-queue][dry-run] {' '.join(cmd)}")
        return None
    try:
        subprocess.run(cmd, cwd=str(paths.root / "crawler"), check=True)
        return None
    except Exception as exc:
        return str(exc)


def cmd_run_queue(args) -> int:
    paths = _paths()
    libraries = _load_libraries(paths)
    queue_path = _resolve_path(paths.root, args.queue_file)
    queue = _load_queue(queue_path)
    now = _now()
    retry_delay = timedelta(minutes=max(1, int(args.retry_delay_min)))
    max_items = max(0, int(args.max_items))

    items = queue.get("items", [])
    pending = [i for i in items if i.get("status") == "pending"]
    pending.sort(key=lambda x: x.get("run_at", ""))

    executed = 0
    for item in pending:
        if max_items and executed >= max_items:
            break

        due = True
        if not args.force_due:
            run_at = _parse_dt(item.get("run_at", "")) or now
            due = run_at <= now
        if not due:
            continue

        lib_code = item.get("lib_code")
        item["status"] = "running"
        item["updated_at"] = _dt_str(_now())
        _save_queue(queue_path, queue)

        error = _execute_crawl(libraries, paths, lib_code=lib_code, dry_run=args.dry_run)
        executed += 1
        if error is None:
            item["status"] = "done" if not args.dry_run else "pending"
            item["last_error"] = ""
            if args.dry_run:
                print(f"[run-queue][dry-run] keep pending: {lib_code}")
            else:
                print(f"[run-queue] done: {lib_code}")
        else:
            item["tries"] = int(item.get("tries", 0)) + 1
            max_retries = int(item.get("max_retries", 1))
            if item["tries"] <= max_retries:
                item["status"] = "pending"
                item["run_at"] = _dt_str(_now() + retry_delay)
                item["last_error"] = error
                print(f"[run-queue] retry scheduled: {lib_code} tries={item['tries']} err={error}")
            else:
                item["status"] = "failed"
                item["last_error"] = error
                print(f"[run-queue] failed: {lib_code} err={error}")
        item["updated_at"] = _dt_str(_now())
        _save_queue(queue_path, queue)

    _save_queue(queue_path, queue)
    print(f"[run-queue] file={queue_path} processed={executed}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Minimal crawl automation module (standalone).")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Refresh/compute local-vs-remote differences.")
    p_scan.add_argument("--mode", choices=["cache", "live"], default="cache")
    p_scan.add_argument("--threshold", type=int, default=10)
    p_scan.add_argument("--remote-in", default="data/remote_counts.json")
    p_scan.add_argument("--remote-out", default="data/auto_remote_counts.json")
    p_scan.add_argument("--candidates-out", default="data/auto_candidates.json")
    p_scan.set_defaults(func=cmd_scan)

    p_add = sub.add_parser("queue-add", help="Add libraries to queue manually.")
    p_add.add_argument("--lib", nargs="+", required=True)
    p_add.add_argument("--action", choices=["immediate", "night", "skip"], default="night")
    p_add.add_argument("--night-time", default="01:00")
    p_add.add_argument("--max-retries", type=int, default=1)
    p_add.add_argument("--queue-file", default="data/auto_crawl_queue.json")
    p_add.set_defaults(func=cmd_queue_add)

    p_qf = sub.add_parser("queue-from-candidates", help="Queue candidates in bulk.")
    p_qf.add_argument("--candidates-file", default="data/auto_candidates.json")
    p_qf.add_argument("--action", choices=["immediate", "night", "skip"], default="night")
    p_qf.add_argument("--night-time", default="01:00")
    p_qf.add_argument("--max-retries", type=int, default=1)
    p_qf.add_argument("--limit", type=int, default=0)
    p_qf.add_argument("--queue-file", default="data/auto_crawl_queue.json")
    p_qf.set_defaults(func=cmd_queue_from_candidates)

    p_qi = sub.add_parser("queue-interactive", help="Choose action per candidate interactively.")
    p_qi.add_argument("--candidates-file", default="data/auto_candidates.json")
    p_qi.add_argument("--night-time", default="01:00")
    p_qi.add_argument("--max-retries", type=int, default=1)
    p_qi.add_argument("--queue-file", default="data/auto_crawl_queue.json")
    p_qi.set_defaults(func=cmd_queue_interactive)

    p_show = sub.add_parser("show-queue", help="Print queue status.")
    p_show.add_argument("--queue-file", default="data/auto_crawl_queue.json")
    p_show.set_defaults(func=cmd_show_queue)

    p_run = sub.add_parser("run-queue", help="Run due queue items sequentially.")
    p_run.add_argument("--queue-file", default="data/auto_crawl_queue.json")
    p_run.add_argument("--max-items", type=int, default=0, help="0 means no limit")
    p_run.add_argument("--retry-delay-min", type=int, default=10)
    p_run.add_argument("--force-due", action="store_true")
    p_run.add_argument("--dry-run", action="store_true")
    p_run.set_defaults(func=cmd_run_queue)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
