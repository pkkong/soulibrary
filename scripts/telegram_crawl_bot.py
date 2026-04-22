import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def _dt_now() -> datetime:
    return datetime.now()


def _dt_str(dt: datetime) -> str:
    return dt.strftime(DATETIME_FMT)


def _parse_dt(text: str) -> Optional[datetime]:
    try:
        return datetime.strptime(text, DATETIME_FMT)
    except Exception:
        return None


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


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


def _resolve_path(root: Path, text: str) -> Path:
    p = Path(text)
    return p if p.is_absolute() else (root / p).resolve()


def _default_config() -> dict:
    return {
        "scan_mode": "cache",
        "threshold": 10,
        "night_time": "23:00",
        "remote_in": "data/remote_counts.json",
        "remote_out": "data/auto_remote_counts.json",
        "candidates_out": "data/auto_candidates.json",
        "queue_file": "data/auto_crawl_queue.json",
        "state_file": "data/telegram_bot_state.json",
        "max_candidates_in_message": 12,
        "max_retries": 1,
        "retry_delay_min": 10,
        "poll_timeout_sec": 25,
        "queue_tick_sec": 60,
        "allow_only_chat_id": True,
        "operations": {
            "local_ingest": {
                "label": "로컬 DB 적재",
                "enabled": True,
                "command": ["{python}", "scripts/load_csv_to_postgres.py"],
                "env": {},
            },
            "cloud_ingest": {
                "label": "Cloudtype DB 업데이트",
                "enabled": False,
                "command": ["{python}", "scripts/load_csv_to_postgres.py"],
                "env": {
                    "DB_HOST": "",
                    "DB_PORT": "",
                    "DB_NAME": "",
                    "DB_USER": "",
                    "DB_PASSWORD": "",
                },
            },
        },
    }


def _load_config(path: Path) -> dict:
    cfg = _default_config()
    saved = _read_json(path, default={})
    if isinstance(saved, dict):
        cfg.update(saved)
    return cfg


def _save_config(path: Path, cfg: dict) -> None:
    _write_json(path, cfg)


def _default_state() -> dict:
    return {"sessions": {}, "updated_at": None}


def _load_state(path: Path) -> dict:
    state = _read_json(path, default=_default_state())
    if not isinstance(state, dict):
        return _default_state()
    if "sessions" not in state or not isinstance(state["sessions"], dict):
        state["sessions"] = {}
    return state


def _save_state(path: Path, state: dict) -> None:
    state["updated_at"] = _dt_str(_dt_now())
    _write_json(path, state)


class TelegramClient:
    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self.session = requests.Session()

    def _post(self, method: str, payload: dict) -> dict:
        url = f"{self.base}/{method}"
        res = self.session.post(url, json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error ({method}): {data}")
        return data.get("result") or {}

    def _get(self, method: str, params: dict) -> dict:
        url = f"{self.base}/{method}"
        res = self.session.get(url, params=params, timeout=35)
        res.raise_for_status()
        data = res.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error ({method}): {data}")
        return data.get("result") or {}

    def send_message(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> dict:
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def edit_message_reply_markup(self, chat_id: str, message_id: int, reply_markup: dict) -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup}
        return self._post("editMessageReplyMarkup", payload)

    def answer_callback(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
        payload = {
            "callback_query_id": callback_query_id,
            "text": text[:180],
            "show_alert": bool(show_alert),
        }
        self._post("answerCallbackQuery", payload)

    def get_updates(self, offset: Optional[int], timeout_sec: int) -> List[dict]:
        params = {"timeout": max(1, int(timeout_sec))}
        if offset is not None:
            params["offset"] = int(offset)
        result = self._get("getUpdates", params)
        return result if isinstance(result, list) else []


def _run_cmd(
    root: Path,
    args: List[str],
    timeout: Optional[int] = None,
    stream: bool = False,
    env: Optional[dict] = None,
) -> Tuple[int, str, str]:
    run_env = os.environ.copy()
    if env:
        for k, v in env.items():
            if v is None:
                continue
            run_env[str(k)] = str(v)

    if not stream:
        proc = subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=run_env,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""

    # Stream combined stdout/stderr to current console in real time.
    out_lines: List[str] = []
    proc = subprocess.Popen(
        args,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=run_env,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip("\r\n")
            print(text, flush=True)
            out_lines.append(text)
            if len(out_lines) > 12000:
                out_lines.pop(0)
        rc = proc.wait(timeout=timeout)
    except Exception:
        proc.kill()
        raise
    return rc, "\n".join(out_lines), ""


def _run_scan(root: Path, cfg: dict) -> Tuple[bool, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "crawl_min_auto.py"),
        "scan",
        "--mode",
        str(cfg.get("scan_mode", "cache")),
        "--threshold",
        str(int(cfg.get("threshold", 10))),
        "--remote-in",
        str(cfg.get("remote_in", "data/remote_counts.json")),
        "--remote-out",
        str(cfg.get("remote_out", "data/auto_remote_counts.json")),
        "--candidates-out",
        str(cfg.get("candidates_out", "data/auto_candidates.json")),
    ]
    code, out, err = _run_cmd(root, cmd, timeout=300)
    if code != 0:
        return False, (out + "\n" + err).strip()
    return True, out.strip()


def _load_candidates(root: Path, cfg: dict) -> dict:
    path = _resolve_path(root, str(cfg.get("candidates_out", "data/auto_candidates.json")))
    data = _read_json(path, default={})
    if not isinstance(data, dict):
        return {"candidates": [], "all": [], "generated_at": None}
    data.setdefault("candidates", [])
    data.setdefault("all", [])
    data.setdefault("generated_at", None)
    return data


def _render_scan_message(report: dict, cfg: dict) -> str:
    candidates = report.get("candidates") or []
    generated_at = report.get("generated_at") or _dt_str(_dt_now())
    threshold = int(cfg.get("threshold", 10))
    mode = str(cfg.get("scan_mode", "cache"))
    lines = [
        f"[자동 점검] {generated_at}",
        f"- mode: {mode}",
        f"- 기준: 차이 {threshold}권 이상",
        f"- 후보: {len(candidates)}개",
        "",
    ]
    if not candidates:
        lines.append("차이 기준을 넘는 도서관이 없습니다.")
    else:
        show_n = min(len(candidates), int(cfg.get("max_candidates_in_message", 12)))
        lines.append("상위 후보:")
        for c in candidates[:show_n]:
            code = c.get("code")
            diff = c.get("diff")
            local_count = c.get("local_count")
            remote_count = c.get("remote_count")
            lines.append(f"- {code}: +{diff} (로컬 {local_count}, 원격 {remote_count})")
        if len(candidates) > show_n:
            lines.append(f"- ... 외 {len(candidates) - show_n}개")
        lines.append("")
        lines.append("아래 버튼에서 실행 대상을 선택하세요.")
    return "\n".join(lines)


def _build_keyboard(session: dict, cfg: dict) -> dict:
    cand_list = session.get("candidates") or []
    selected = set(session.get("selected") or [])
    rows = []
    for c in cand_list:
        code = c.get("code")
        if not code:
            continue
        diff = c.get("diff")
        mark = "✅" if code in selected else "⬜"
        label = f"{mark} {code} (+{diff})"
        rows.append([{"text": label[:56], "callback_data": f"tg:{code}"}])

    night_time = str(session.get("night_time") or cfg.get("night_time", "23:00"))
    rows.append(
        [
            {"text": "전체선택", "callback_data": "all"},
            {"text": "전체해제", "callback_data": "none"},
        ]
    )
    rows.append(
        [
            {"text": "즉시 실행", "callback_data": "run:now"},
            {"text": f"야간 예약({night_time})", "callback_data": "run:night"},
        ]
    )
    rows.append([{"text": "상태 보기", "callback_data": "status"}])
    return {"inline_keyboard": rows}


def _build_ops_keyboard(cfg: dict) -> dict:
    ops = cfg.get("operations") or {}
    rows = []
    for key in ["local_ingest", "cloud_ingest"]:
        op = ops.get(key) or {}
        if not bool(op.get("enabled", False)):
            continue
        label = str(op.get("label") or key)
        rows.append([{"text": label[:56], "callback_data": f"op:{key}"}])
    rows.append([{"text": "큐 상태 보기", "callback_data": "op:status"}])
    return {"inline_keyboard": rows}


def _queue_add(root: Path, cfg: dict, codes: List[str], action: str, night_time: str) -> Tuple[bool, str]:
    if not codes:
        return False, "선택된 도서관이 없습니다."

    cmd = [
        sys.executable,
        str(root / "scripts" / "crawl_min_auto.py"),
        "queue-add",
        "--lib",
        *codes,
        "--action",
        action,
        "--max-retries",
        str(int(cfg.get("max_retries", 1))),
        "--queue-file",
        str(cfg.get("queue_file", "data/auto_crawl_queue.json")),
    ]
    if action == "night":
        cmd.extend(["--night-time", night_time])

    code, out, err = _run_cmd(root, cmd, timeout=180)
    text = (out + "\n" + err).strip()
    return code == 0, text or "(no output)"


def _run_due_queue(root: Path, cfg: dict, max_items: int = 0) -> Tuple[bool, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "crawl_min_auto.py"),
        "run-queue",
        "--queue-file",
        str(cfg.get("queue_file", "data/auto_crawl_queue.json")),
        "--retry-delay-min",
        str(int(cfg.get("retry_delay_min", 10))),
    ]
    if max_items > 0:
        cmd.extend(["--max-items", str(int(max_items))])
    code, out, err = _run_cmd(root, cmd, timeout=None, stream=True)
    text = (out + "\n" + err).strip()
    return code == 0, text or "(no output)"


def _queue_counts(root: Path, cfg: dict) -> dict:
    queue_path = _resolve_path(root, str(cfg.get("queue_file", "data/auto_crawl_queue.json")))
    data = _read_json(queue_path, default={})
    if not isinstance(data, dict):
        return {"pending": 0, "running": 0, "done": 0, "failed": 0, "total": 0}
    items = data.get("items") or []
    return {
        "pending": sum(1 for i in items if i.get("status") == "pending"),
        "running": sum(1 for i in items if i.get("status") == "running"),
        "done": sum(1 for i in items if i.get("status") == "done"),
        "failed": sum(1 for i in items if i.get("status") == "failed"),
        "total": len(items),
    }


def _queue_summary(root: Path, cfg: dict) -> str:
    c = _queue_counts(root, cfg)
    return (
        f"[큐 상태] pending={c['pending']}, running={c['running']}, "
        f"done={c['done']}, failed={c['failed']}, total={c['total']}"
    )


def _status_map_for_codes(root: Path, cfg: dict, codes: List[str]) -> Dict[str, str]:
    queue_path = _resolve_path(root, str(cfg.get("queue_file", "data/auto_crawl_queue.json")))
    data = _read_json(queue_path, default={})
    if not isinstance(data, dict):
        return {c: "unknown" for c in codes}
    items = data.get("items") or []
    by_code: Dict[str, Tuple[datetime, str]] = {}
    for item in items:
        code = item.get("lib_code")
        if code not in codes:
            continue
        stamp = _parse_dt(str(item.get("updated_at") or "")) or datetime.min
        st = str(item.get("status") or "unknown")
        prev = by_code.get(code)
        if (prev is None) or (stamp >= prev[0]):
            by_code[code] = (stamp, st)
    return {c: by_code.get(c, (datetime.min, "unknown"))[1] for c in codes}


def _resolve_op_command(root: Path, cmd_def: List[str]) -> List[str]:
    out = []
    for token in cmd_def:
        text = str(token)
        if text == "{python}":
            out.append(sys.executable)
            continue
        if text.startswith("{root}/"):
            rel = text.replace("{root}/", "", 1).replace("/", os.sep)
            out.append(str((root / rel).resolve()))
            continue
        out.append(text)
    return out


def _run_operation(root: Path, cfg: dict, op_key: str) -> Tuple[bool, str]:
    ops = cfg.get("operations") or {}
    op = ops.get(op_key) or {}
    if not bool(op.get("enabled", False)):
        return False, f"operation not enabled: {op_key}"
    cmd_def = op.get("command") or []
    if not isinstance(cmd_def, list) or not cmd_def:
        return False, f"invalid command config: {op_key}"

    queue = _queue_counts(root, cfg)
    if queue["running"] > 0 or queue["pending"] > 0:
        return False, (
            "crawl queue is not empty "
            f"(pending={queue['pending']}, running={queue['running']})."
        )

    env_overrides = op.get("env") or {}
    cmd = _resolve_op_command(root, cmd_def)
    code, out, err = _run_cmd(root, cmd, timeout=None, stream=True, env=env_overrides)
    text = (out + "\n" + err).strip()
    return code == 0, text or "(no output)"


def _due_pending_count(root: Path, cfg: dict) -> int:
    queue_path = _resolve_path(root, str(cfg.get("queue_file", "data/auto_crawl_queue.json")))
    data = _read_json(queue_path, default={})
    if not isinstance(data, dict):
        return 0
    items = data.get("items") or []
    now = _dt_now()
    due = 0
    for item in items:
        if item.get("status") != "pending":
            continue
        run_at = _parse_dt(str(item.get("run_at") or "")) or now
        if run_at <= now:
            due += 1
    return due


def _is_allowed_chat(chat_id: str, cfg: dict, env_chat_id: Optional[str]) -> bool:
    if not bool(cfg.get("allow_only_chat_id", True)):
        return True
    if not env_chat_id:
        return True
    return str(chat_id) == str(env_chat_id)


def _make_session(report: dict, cfg: dict) -> dict:
    candidates = report.get("candidates") or []
    max_n = int(cfg.get("max_candidates_in_message", 12))
    selected_candidates = candidates[:max_n]
    return {
        "generated_at": report.get("generated_at") or _dt_str(_dt_now()),
        "candidates": selected_candidates,
        "selected": [c.get("code") for c in selected_candidates if c.get("code")],
        "night_time": str(cfg.get("night_time", "23:00")),
    }


def _scan_notify(root: Path, cfg: dict, tg: TelegramClient, chat_id: str, state: dict, state_path: Path) -> Tuple[bool, str]:
    ok, output = _run_scan(root, cfg)
    if not ok:
        tg.send_message(chat_id, f"[자동 점검 실패]\n{output[:3500]}")
        return False, output

    report = _load_candidates(root, cfg)
    session = _make_session(report, cfg)
    text = _render_scan_message(report, cfg)
    keyboard = _build_keyboard(session, cfg)
    sent = tg.send_message(chat_id, text, reply_markup=keyboard)

    chat_key = str(chat_id)
    sess = dict(session)
    sess["message_id"] = int(sent.get("message_id", 0))
    state["sessions"][chat_key] = sess
    _save_state(state_path, state)
    return True, output


class QueueRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = False

    def run_async(self, fn, *args, **kwargs) -> bool:
        with self.lock:
            if self.active:
                return False
            self.active = True

        def _target():
            try:
                fn(*args, **kwargs)
            finally:
                with self.lock:
                    self.active = False

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        return True


def _handle_message(
    msg: dict,
    root: Path,
    cfg: dict,
    config_path: Path,
    tg: TelegramClient,
    env_chat_id: Optional[str],
    state: dict,
    state_path: Path,
    runner: QueueRunner,
) -> None:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id"))
    if not _is_allowed_chat(chat_id, cfg, env_chat_id):
        return

    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/start") or text.startswith("/help"):
        tg.send_message(
            chat_id,
            "\n".join(
                [
                    "Seoulib Crawl Bot",
                    "- /scan : 권수 차이 점검 + 선택 버튼 전송",
                    "- /status : 큐 상태 보기",
                    "- /night HH:MM : 야간 예약 시간 변경 (예: /night 23:30)",
                    "- /run_due : 지금 시점 도래한 큐 실행",
                    "- /ops : DB 작업 버튼 열기(로컬 적재/Cloudtype 업데이트)",
                ]
            ),
        )
        return

    if text.startswith("/scan"):
        ok, result = _scan_notify(root, cfg, tg, chat_id, state, state_path)
        if not ok:
            tg.send_message(chat_id, f"[scan 실패]\n{result[:3500]}")
        return

    if text.startswith("/status"):
        tg.send_message(chat_id, _queue_summary(root, cfg))
        return

    if text.startswith("/night"):
        parts = text.split()
        if len(parts) != 2 or ":" not in parts[1]:
            tg.send_message(chat_id, "형식: /night HH:MM  (예: /night 23:00)")
            return
        cfg["night_time"] = parts[1].strip()
        _save_config(config_path, cfg)
        tg.send_message(chat_id, f"야간 예약 시간을 {cfg['night_time']}로 변경했습니다.")
        return

    if text.startswith("/run_due"):
        def _job():
            ok_run, out_run = _run_due_queue(root, cfg, max_items=0)
            prefix = "[run_due 완료]" if ok_run else "[run_due 실패]"
            tg.send_message(chat_id, f"{prefix}\n{out_run[:3500]}")

        if runner.run_async(_job):
            tg.send_message(chat_id, "도래한 큐 실행을 시작했습니다.")
        else:
            tg.send_message(chat_id, "이미 실행 중인 작업이 있습니다.")
        return

    if text.startswith("/ops"):
        tg.send_message(
            chat_id,
            "DB 작업을 선택하세요. (큐가 비어있을 때만 실행됩니다.)",
            reply_markup=_build_ops_keyboard(cfg),
        )
        return


def _handle_callback(
    cb: dict,
    root: Path,
    cfg: dict,
    tg: TelegramClient,
    env_chat_id: Optional[str],
    state: dict,
    state_path: Path,
    runner: QueueRunner,
) -> None:
    cb_id = cb.get("id")
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id"))
    message_id = int(msg.get("message_id") or 0)

    if not _is_allowed_chat(chat_id, cfg, env_chat_id):
        try:
            tg.answer_callback(cb_id, "허용되지 않은 채팅입니다.", show_alert=True)
        except Exception:
            pass
        return

    if data == "op:status":
        tg.answer_callback(cb_id, _queue_summary(root, cfg), show_alert=True)
        return

    if data.startswith("op:"):
        op_key = data.split(":", 1)[1]
        ops = cfg.get("operations") or {}
        op_cfg = ops.get(op_key) or {}
        label = str(op_cfg.get("label") or op_key)

        if runner.active:
            tg.answer_callback(cb_id, "현재 실행중인 작업이 있습니다.", show_alert=True)
            return

        queue = _queue_counts(root, cfg)
        if queue["running"] > 0 or queue["pending"] > 0:
            tg.answer_callback(
                cb_id,
                f"큐가 비어있지 않습니다 (pending={queue['pending']}, running={queue['running']}).",
                show_alert=True,
            )
            return

        def _op_job():
            ok_op, out_op = _run_operation(root, cfg, op_key=op_key)
            title = f"[{label} 완료]" if ok_op else f"[{label} 실패]"
            tg.send_message(
                chat_id,
                "\n".join(
                    [
                        title,
                        f"- queue: { _queue_summary(root, cfg) }",
                        "",
                        out_op[:3500],
                    ]
                ),
            )

        if runner.run_async(_op_job):
            tg.answer_callback(cb_id, f"{label} 시작", show_alert=False)
            tg.send_message(chat_id, f"[{label} 시작]")
        else:
            tg.answer_callback(cb_id, "현재 실행중인 작업이 있습니다.", show_alert=True)
        return

    sess = state.get("sessions", {}).get(str(chat_id))
    if not sess:
        tg.answer_callback(cb_id, "세션이 없습니다. /scan을 먼저 실행하세요.", show_alert=True)
        return
    if int(sess.get("message_id") or 0) != message_id:
        tg.answer_callback(cb_id, "이전 메시지입니다. /scan을 다시 실행하세요.", show_alert=False)
        return

    candidates = sess.get("candidates") or []
    cand_codes = [c.get("code") for c in candidates if c.get("code")]
    selected = set(sess.get("selected") or [])

    if data.startswith("tg:"):
        code = data.split(":", 1)[1]
        if code in selected:
            selected.remove(code)
        elif code in cand_codes:
            selected.add(code)
        sess["selected"] = [c for c in cand_codes if c in selected]
        state["sessions"][str(chat_id)] = sess
        _save_state(state_path, state)
        tg.edit_message_reply_markup(chat_id, message_id, _build_keyboard(sess, cfg))
        tg.answer_callback(cb_id, f"선택: {len(sess['selected'])}개", show_alert=False)
        return

    if data == "all":
        sess["selected"] = list(cand_codes)
        state["sessions"][str(chat_id)] = sess
        _save_state(state_path, state)
        tg.edit_message_reply_markup(chat_id, message_id, _build_keyboard(sess, cfg))
        tg.answer_callback(cb_id, "전체 선택", show_alert=False)
        return

    if data == "none":
        sess["selected"] = []
        state["sessions"][str(chat_id)] = sess
        _save_state(state_path, state)
        tg.edit_message_reply_markup(chat_id, message_id, _build_keyboard(sess, cfg))
        tg.answer_callback(cb_id, "전체 해제", show_alert=False)
        return

    if data == "status":
        tg.answer_callback(cb_id, _queue_summary(root, cfg), show_alert=True)
        return

    if data in {"run:now", "run:night"}:
        selected_codes = list(sess.get("selected") or [])
        if not selected_codes:
            tg.answer_callback(cb_id, "선택된 도서관이 없습니다.", show_alert=True)
            return
        night_time = str(sess.get("night_time") or cfg.get("night_time", "23:00"))
        action = "immediate" if data == "run:now" else "night"

        ok_add, out_add = _queue_add(root, cfg, selected_codes, action=action, night_time=night_time)
        if not ok_add:
            tg.answer_callback(cb_id, "큐 추가 실패", show_alert=True)
            tg.send_message(chat_id, f"[큐 추가 실패]\n{out_add[:3500]}")
            return

        if action == "night":
            tg.answer_callback(cb_id, f"야간 예약 완료 ({night_time})", show_alert=False)
            tg.send_message(
                chat_id,
                "\n".join(
                    [
                        f"[야간 예약 완료] {len(selected_codes)}개",
                        f"- 실행 시간: {night_time}",
                        f"- 대상: {', '.join(selected_codes)}",
                        "",
                        out_add[:2200],
                    ]
                ),
            )
            return

        def _job():
            ok_run, out_run = _run_due_queue(root, cfg, max_items=max(1, len(selected_codes)))
            status_map = _status_map_for_codes(root, cfg, selected_codes)
            done_n = sum(1 for s in status_map.values() if s == "done")
            running_n = sum(1 for s in status_map.values() if s == "running")
            pending_n = sum(1 for s in status_map.values() if s == "pending")
            failed_n = sum(1 for s in status_map.values() if s == "failed")

            if failed_n > 0 and done_n == 0 and running_n == 0 and pending_n == 0:
                title = "[즉시 실행 실패]"
            elif running_n > 0 or pending_n > 0:
                title = "[즉시 실행 진행중]"
            elif failed_n > 0 and done_n > 0:
                title = "[즉시 실행 일부 실패]"
            elif done_n > 0:
                title = "[즉시 실행 완료]"
            else:
                title = "[즉시 실행 결과확인필요]"

            tg.send_message(
                chat_id,
                "\n".join(
                    [
                        f"{title} 대상={len(selected_codes)}",
                        f"- 선택: {', '.join(selected_codes)}",
                        f"- 상태: {status_map}",
                        f"- 실행기 종료코드 기준: {'ok' if ok_run else 'error'}",
                        "",
                        out_add[:1500],
                        "",
                        out_run[:1800],
                    ]
                ),
            )

        started = runner.run_async(_job)
        if started:
            tg.answer_callback(cb_id, "즉시 실행을 시작했습니다.", show_alert=False)
            tg.send_message(chat_id, f"[즉시 실행 시작] {', '.join(selected_codes)}")
        else:
            tg.answer_callback(cb_id, "이미 실행 중인 작업이 있습니다.", show_alert=True)
        return

    tg.answer_callback(cb_id, "지원하지 않는 동작입니다.", show_alert=False)


def cmd_scan_notify(args) -> int:
    root = _root_dir()
    config_path = _resolve_path(root, args.config_file)
    cfg = _load_config(config_path)

    token = os.getenv("SEOULIB_TG_BOT_TOKEN", "").strip()
    chat_id = os.getenv("SEOULIB_TG_CHAT_ID", "").strip()
    if not token:
        print("SEOULIB_TG_BOT_TOKEN is required.")
        return 2
    if not chat_id:
        print("SEOULIB_TG_CHAT_ID is required.")
        return 2

    tg = TelegramClient(token)
    state_path = _resolve_path(root, str(cfg.get("state_file", "data/telegram_bot_state.json")))
    state = _load_state(state_path)
    ok, out = _scan_notify(root, cfg, tg, chat_id, state, state_path)
    print(out)
    return 0 if ok else 1


def cmd_detect_chat_id(args) -> int:
    token = os.getenv("SEOULIB_TG_BOT_TOKEN", "").strip()
    if not token:
        print("SEOULIB_TG_BOT_TOKEN is required.")
        return 2
    tg = TelegramClient(token)
    updates = tg.get_updates(offset=None, timeout_sec=1)
    if not updates:
        print("No updates. Send /start to your bot, then rerun.")
        return 1
    seen = []
    for u in updates:
        msg = u.get("message") or (u.get("callback_query") or {}).get("message") or {}
        chat = msg.get("chat") or {}
        if "id" not in chat:
            continue
        cid = str(chat["id"])
        ctype = str(chat.get("type") or "")
        title = str(chat.get("title") or chat.get("username") or "")
        seen.append((cid, ctype, title))

    uniq = []
    added = set()
    for row in seen:
        if row[0] in added:
            continue
        added.add(row[0])
        uniq.append(row)

    if not uniq:
        print("No chat id found in updates.")
        return 1

    print("Detected chat ids:")
    for cid, ctype, title in uniq:
        print(f"- chat_id={cid} type={ctype} title={title}")
    return 0


def cmd_bot_loop(args) -> int:
    root = _root_dir()
    config_path = _resolve_path(root, args.config_file)
    cfg = _load_config(config_path)
    _save_config(config_path, cfg)

    token = os.getenv("SEOULIB_TG_BOT_TOKEN", "").strip()
    env_chat_id = os.getenv("SEOULIB_TG_CHAT_ID", "").strip()
    if not token:
        print("SEOULIB_TG_BOT_TOKEN is required.")
        return 2

    tg = TelegramClient(token)
    state_path = _resolve_path(root, str(cfg.get("state_file", "data/telegram_bot_state.json")))
    state = _load_state(state_path)
    runner = QueueRunner()

    offset = None
    if not args.read_history:
        try:
            latest = tg.get_updates(offset=None, timeout_sec=1)
            if latest:
                offset = int(latest[-1].get("update_id", 0)) + 1
        except Exception:
            pass

    poll_timeout = int(cfg.get("poll_timeout_sec", 25))
    queue_tick = max(10, int(cfg.get("queue_tick_sec", 60)))
    next_tick = 0.0

    print("[bot] started. Press Ctrl+C to stop.")
    if env_chat_id:
        print(f"[bot] allow chat_id = {env_chat_id}")
    else:
        print("[bot] allow chat_id = ANY (SEOULIB_TG_CHAT_ID not set)")

    try:
        while True:
            now_ts = time.time()
            if now_ts >= next_tick:
                next_tick = now_ts + queue_tick
                if not runner.active:
                    due_count = _due_pending_count(root, cfg)
                    if due_count > 0:
                        def _tick_job():
                            ok_run, out_run = _run_due_queue(root, cfg, max_items=0)
                            target_chat = env_chat_id
                            if target_chat:
                                title = "[자동 큐 실행 완료]" if ok_run else "[자동 큐 실행 실패]"
                                tg.send_message(str(target_chat), f"{title}\n{out_run[:3500]}")

                        runner.run_async(_tick_job)

            updates = tg.get_updates(offset=offset, timeout_sec=poll_timeout)
            if not updates:
                continue
            for u in updates:
                offset = int(u.get("update_id", 0)) + 1
                if "message" in u:
                    _handle_message(
                        u["message"],
                        root=root,
                        cfg=cfg,
                        config_path=config_path,
                        tg=tg,
                        env_chat_id=env_chat_id if env_chat_id else None,
                        state=state,
                        state_path=state_path,
                        runner=runner,
                    )
                elif "callback_query" in u:
                    _handle_callback(
                        u["callback_query"],
                        root=root,
                        cfg=cfg,
                        tg=tg,
                        env_chat_id=env_chat_id if env_chat_id else None,
                        state=state,
                        state_path=state_path,
                        runner=runner,
                    )
                _save_state(state_path, state)
            if args.once:
                break
    except KeyboardInterrupt:
        print("[bot] stopped by user.")
        return 0
    except Exception as exc:
        print(f"[bot] fatal error: {exc}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Telegram-based crawl automation bridge.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan-notify", help="Run scan and send candidate message to Telegram.")
    p_scan.add_argument("--config-file", default="data/telegram_bot_config.json")
    p_scan.set_defaults(func=cmd_scan_notify)

    p_loop = sub.add_parser("bot-loop", help="Run Telegram long-polling loop.")
    p_loop.add_argument("--config-file", default="data/telegram_bot_config.json")
    p_loop.add_argument("--once", action="store_true", help="Process one polling cycle and exit.")
    p_loop.add_argument("--read-history", action="store_true", help="Process old pending updates too.")
    p_loop.set_defaults(func=cmd_bot_loop)

    p_chat = sub.add_parser("detect-chat-id", help="Detect chat_id from getUpdates.")
    p_chat.set_defaults(func=cmd_detect_chat_id)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
