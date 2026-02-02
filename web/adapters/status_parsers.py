import re

def _to_int(value, default=0):
    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return default


def parse_kyobo_status(html: str):
    if not html:
        return None
    match = re.search(r'<p class="use">.*?</p>', html, re.S)
    text = match.group(0) if match else html
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    numbers = re.search(r"대출\s*:\s*([\d,]+)\s*/\s*([\d,]+)\s*예약\s*:\s*([\d,]+)", text)
    if not numbers:
        return None
    loaned = int(numbers.group(1).replace(",", ""))
    total = int(numbers.group(2).replace(",", ""))
    reserved = int(numbers.group(3).replace(",", ""))
    return {"loaned": loaned, "total": total, "reserved": reserved}


def parse_bookcube_status(html: str, content_id: str):
    if not html or not content_id:
        return None
    blocks = re.findall(r"<li class=\"item\".*?</li>", html, re.S)
    for block in blocks:
        if content_id not in block:
            continue
        text = re.sub(r"<[^>]+>", " ", block)
        text = re.sub(r"\s+", " ", text)
        loan_match = re.search(r"대출\s*([0-9,]+)\s*/\s*([0-9,]+)", text)
        reserve_match = re.search(r"예약\s*([0-9,]+)", text)
        if loan_match:
            return {
                "loaned": int(loan_match.group(1).replace(",", "")),
                "total": int(loan_match.group(2).replace(",", "")),
                "reserved": int(reserve_match.group(1).replace(",", "")) if reserve_match else 0,
            }

    idx = html.find(content_id)
    if idx == -1:
        return None
    start = max(idx - 4000, 0)
    end = min(idx + 4000, len(html))
    chunk = html[start:end]
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = re.sub(r"\s+", " ", text)
    loan_match = re.search(r"대출\s*([0-9,]+)\s*/\s*([0-9,]+)", text)
    reserve_match = re.search(r"예약\s*([0-9,]+)", text)
    if loan_match:
        return {
            "loaned": int(loan_match.group(1).replace(",", "")),
            "total": int(loan_match.group(2).replace(",", "")),
            "reserved": int(reserve_match.group(1).replace(",", "")) if reserve_match else 0,
        }
    return None


def parse_bookcube_detail_status(html: str):
    if not html:
        return None
    def _sanitize_status(status):
        if not status:
            return None
        if status.get("loaned") == 0 and status.get("total") == 0 and status.get("reserved") == 0:
            return None
        return status
    block_match = re.search(r"<ul[^>]*class=['\"]state['\"][^>]*>(.*?)</ul>", html, re.I | re.S)
    block = block_match.group(1) if block_match else ""
    if block:
        m = re.search(r"<p[^>]*>\s*\uB300\uCD9C\s*</p>\s*([0-9,]+)\s*/\s*([0-9,]+)", block, re.I)
        r = re.search(r"<p[^>]*>\s*\uC608\uC57D\s*</p>\s*([0-9,]+)", block, re.I)
        if m:
            return _sanitize_status({
                "loaned": int(m.group(1).replace(",", "")),
                "total": int(m.group(2).replace(",", "")),
                "reserved": int(r.group(1).replace(",", "")) if r else 0,
            })
        m = re.search(r"\uB300\uCD9C[^0-9]*([0-9,]+)\s*/\s*([0-9,]+)", block, re.I | re.S)
        r = re.search(r"\uC608\uC57D[^0-9]*([0-9,]+)", block, re.I | re.S)
        if m:
            return _sanitize_status({
                "loaned": int(m.group(1).replace(",", "")),
                "total": int(m.group(2).replace(",", "")),
                "reserved": int(r.group(1).replace(",", "")) if r else 0,
            })
    text_only = re.sub(r"<[^>]+>", " ", html)
    text_only = re.sub(r"\s+", " ", text_only)
    loan_match = re.search(r"\uB300\uCD9C\s*([0-9,]+)\s*/\s*([0-9,]+)", text_only)
    reserve_match = re.search(r"\uC608\uC57D\s*([0-9,]+)", text_only)
    if loan_match:
        return _sanitize_status({
            "loaned": int(loan_match.group(1).replace(",", "")),
            "total": int(loan_match.group(2).replace(",", "")),
            "reserved": int(reserve_match.group(1).replace(",", "")) if reserve_match else 0,
        })
    return None


def parse_gangnam_status(html: str, content_id: str):
    if not html or not content_id:
        return None
    needle = f"book_num={content_id}"
    idx = html.find(needle)
    if idx == -1:
        return None
    start = max(idx - 5000, 0)
    end = min(idx + 5000, len(html))
    chunk = html[start:end]
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = re.sub(r"\s+", " ", text)
    owned_match = re.search(r"보유\s*(\d+)", text)
    loan_match = re.search(r"대출\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if not loan_match or not owned_match:
        return None
    return {
        "owned": int(owned_match.group(1)),
        "loaned": int(loan_match.group(1)),
        "reserved": int(reserve_match.group(1)) if reserve_match else 0,
    }


def parse_gangnam_detail_status(html: str):
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    owned_match = re.search(r"보유\s*(\d+)", text)
    loan_match = re.search(r"대출\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if not loan_match or not owned_match:
        return None
    return {
        "owned": int(owned_match.group(1)),
        "loaned": int(loan_match.group(1)),
        "reserved": int(reserve_match.group(1)) if reserve_match else 0,
    }


def parse_yes24_status(html: str, goods_id: str = ""):
    if not html:
        return None
    stat_match = re.search(r'<div class="stat[^\"]*">.*?</div>', html, re.S)
    if stat_match:
        stat_html = stat_match.group(0)
        def pick(label):
            m = re.search(rf"<li>\s*{label}\s*<strong>(\d+)</strong>", stat_html)
            return int(m.group(1)) if m else 0
        return {
            "owned": pick("보유"),
            "loaned": pick("대출"),
            "reserved": pick("예약"),
        }

    if goods_id:
        parts = html.split('<div class="bx')
        for part in parts[1:]:
            block = '<div class="bx' + part
            if f"goods_id={goods_id}" not in block:
                continue
            stat_match = re.search(r'<div class="stat">.*?</div>', block, re.S)
            if not stat_match:
                return None
            stat_html = stat_match.group(0)
            def pick(label):
                m = re.search(rf"<li>\s*{label}\s*<strong>(\d+)</strong>", stat_html)
                return int(m.group(1)) if m else 0
            return {
                "owned": pick("보유"),
                "loaned": pick("대출"),
                "reserved": pick("예약"),
            }
    return None


def parse_seoul_status(data: dict):
    contents = data.get("Contents") if isinstance(data, dict) else None
    if isinstance(contents, list) and contents:
        contents = contents[0]
    if not isinstance(contents, dict):
        return None
    return {
        "loaned": _to_int(contents.get("currentLoanCount")),
        "total": _to_int(contents.get("contentsCopys")),
        "reserved": _to_int(contents.get("currentResvCount")),
    }


def parse_sen_status(data: dict):
    contents = data.get("Contents") if isinstance(data, dict) else None
    if isinstance(contents, list) and contents:
        contents = contents[0]
    if isinstance(contents, dict):
        return {
            "loaned": _to_int(contents.get("currentLoanCount")),
            "total": _to_int(contents.get("contentsCopys")),
            "reserved": _to_int(contents.get("currentResvCount")),
        }
    return {
        "loaned": _to_int(data.get("currentLoanCount")),
        "total": _to_int(data.get("contentsCopys")),
        "reserved": _to_int(data.get("currentResvCount")),
    }


def parse_sen_xml_status(xml: str):
    if not xml:
        return None
    loan_match = re.search(r"<currentLoanCount>(\d+)</currentLoanCount>", xml)
    total_match = re.search(r"<contentsCopys>(\d+)</contentsCopys>", xml)
    reserve_match = re.search(r"<currentResvCount>(\d+)</currentResvCount>", xml)
    if loan_match or total_match or reserve_match:
        return {
            "loaned": _to_int(loan_match.group(1) if loan_match else 0),
            "total": _to_int(total_match.group(1) if total_match else 0),
            "reserved": _to_int(reserve_match.group(1) if reserve_match else 0),
        }
    loan_match = re.search(r"<loanCnt>(\d+)</loanCnt>", xml)
    total_match = re.search(r"<contentsCopys>(\d+)</contentsCopys>", xml)
    reserve_match = re.search(r"<reserveCnt>(\d+)</reserveCnt>", xml)
    if loan_match or total_match or reserve_match:
        return {
            "loaned": _to_int(loan_match.group(1) if loan_match else 0),
            "total": _to_int(total_match.group(1) if total_match else 0),
            "reserved": _to_int(reserve_match.group(1) if reserve_match else 0),
        }
    return None


def parse_eunpyeong_status(data: dict):
    contents = data.get("Contents") if isinstance(data, dict) else None
    if isinstance(contents, dict):
        total = _to_int(contents.get("ContentsCopys") or contents.get("Copys"))
        loaned = _to_int(contents.get("CurrentLoanCount") or contents.get("ContentLoanCount"))
        reserved = _to_int(contents.get("CurrentResvCount") or contents.get("ContentResevCount"))
        return {
            "loaned": loaned,
            "total": total,
            "reserved": reserved,
        }
    return None


def parse_eunpyeong_html_status(html: str):
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    loan_match = re.search(r"대출\s*(\d+)\s*/\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if loan_match:
        return {
            "loaned": int(loan_match.group(1)),
            "total": int(loan_match.group(2)),
            "reserved": int(reserve_match.group(1)) if reserve_match else 0,
        }
    return None


def parse_dobong_status(html: str):
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    loan_match = re.search(r"대출\s*(\d+)\s*/\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if loan_match:
        return {
            "loaned": int(loan_match.group(1)),
            "total": int(loan_match.group(2)),
            "reserved": int(reserve_match.group(1)) if reserve_match else 0,
        }
    rent_match = re.search(r'class=["\']rentEbook["\'][^>]*>\s*(\d+)\s*<', html, re.I)
    reserve_match = re.search(r'class=["\']reserveEbook["\'][^>]*>\s*(\d+)\s*<', html, re.I)
    total_match = re.search(r'class=["\']book_present["\'][^>]*>.*?/\s*(\d+)', html, re.I | re.S)
    if rent_match and total_match:
        return {
            "loaned": int(rent_match.group(1)),
            "total": int(total_match.group(1)),
            "reserved": int(reserve_match.group(1)) if reserve_match else 0,
        }
    return None
