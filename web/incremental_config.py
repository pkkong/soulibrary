import math


INCREMENTAL_LIBRARY_SETTINGS = {
    "gwangjin_subs": {
        "kind": "kyobo_new_subs",
        "page_size": 80,
        "min_pages_floor": 12,
        "min_pages_multiplier": 4,
        "max_pages_multiplier": 8,
        "max_pages_buffer": 8,
        "hard_cap": 120,
        "stop_after_known_pages": 3,
    },
    "gangdong_subs": {
        "kind": "kyobo_new_subs",
        "page_size": 80,
        "min_pages_floor": 12,
        "min_pages_multiplier": 4,
        "max_pages_multiplier": 8,
        "max_pages_buffer": 8,
        "hard_cap": 120,
        "stop_after_known_pages": 3,
    },
    "seodaemun_subs": {
        "kind": "kyobo_new_subs",
        "page_size": 80,
        "min_pages_floor": 12,
        "min_pages_multiplier": 4,
        "max_pages_multiplier": 8,
        "max_pages_buffer": 8,
        "hard_cap": 120,
        "stop_after_known_pages": 3,
    },
    "songpa_subs": {
        "kind": "kyobo_new_subs",
        "page_size": 80,
        "min_pages_floor": 12,
        "min_pages_multiplier": 4,
        "max_pages_multiplier": 8,
        "max_pages_buffer": 8,
        "hard_cap": 120,
        "stop_after_known_pages": 3,
    },
    "yangcheon_subs": {
        "kind": "kyobo_new_subs",
        "page_size": 80,
        "min_pages_floor": 12,
        "min_pages_multiplier": 4,
        "max_pages_multiplier": 8,
        "max_pages_buffer": 8,
        "hard_cap": 120,
        "stop_after_known_pages": 3,
    },
    "sen_subs": {
        "kind": "sen_subs_api",
        "page_size": 1000,
        "min_pages_floor": 2,
        "min_pages_multiplier": 2,
        "max_pages_multiplier": 5,
        "max_pages_buffer": 2,
        "hard_cap": 20,
        "stop_after_known_pages": 2,
    },
}


def supports_incremental(lib_code: str) -> bool:
    return lib_code in INCREMENTAL_LIBRARY_SETTINGS


def incremental_settings(lib_code: str) -> dict:
    return dict(INCREMENTAL_LIBRARY_SETTINGS[lib_code])


def build_incremental_plan(lib_code: str, local_count: int, remote_count: int) -> dict:
    settings = incremental_settings(lib_code)
    page_size = int(settings["page_size"])
    diff_count = max(int(remote_count) - int(local_count), 0) if int(remote_count) >= 0 else 0
    expected_pages = max(1, int(math.ceil(diff_count / float(page_size)))) if diff_count > 0 else 1

    min_pages = max(
        int(settings["min_pages_floor"]),
        expected_pages * int(settings["min_pages_multiplier"]),
    )
    max_pages = max(
        min_pages + int(settings["max_pages_buffer"]),
        expected_pages * int(settings["max_pages_multiplier"]),
    )
    max_pages = min(int(settings["hard_cap"]), max_pages)

    return {
        "lib_code": lib_code,
        "kind": settings["kind"],
        "page_size": page_size,
        "local_count": int(local_count),
        "remote_count": int(remote_count),
        "diff_count": diff_count,
        "expected_pages": expected_pages,
        "min_pages": min_pages,
        "max_pages": max_pages,
        "stop_after_known_pages": int(settings["stop_after_known_pages"]),
        "hard_cap": int(settings["hard_cap"]),
    }
