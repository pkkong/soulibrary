import re
from urllib.parse import parse_qs, urlparse

from lxml import html as lxml_html

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


def _explicit_count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", value):
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def _valid_content_id(content_id):
    return isinstance(content_id, str) and re.fullmatch(r"[A-Za-z0-9]{1,64}", content_id)


def _has_class(node, name):
    return name in (node.get("class") or "").split()


def _nearest_class(node, name):
    return next((parent for parent in node.iterancestors() if _has_class(parent, name)), None)


def _html_doc(document):
    return lxml_html.fromstring(document, parser=lxml_html.HTMLParser(remove_comments=True))


def _class_nodes(node, tag, name):
    return node.xpath(f".//{tag}[contains(concat(' ',normalize-space(@class),' '),' {name} ')]")


def _product_link_id(href, platform):
    if platform == "bookcube" and re.match(r"\s*javascript:\s*goView\b", href, re.I):
        match = re.fullmatch(r"\s*javascript:\s*goView\(\s*(['\"])([A-Za-z0-9]+)\1(?:\s*,[^)]*)?\)\s*;?\s*", href, re.I)
        return match.group(2) if match else False
    parsed = urlparse(href)
    paths, key = (("/FxLibrary/product/view",), "num") if platform == "bookcube" else (
        ("/elibbook/book_detail.asp", "book_detail.asp"), "book_num")
    if parsed.path.rstrip("/") not in paths:
        return None
    values = parse_qs(parsed.query, keep_blank_values=True).get(key, [])
    return values[0] if len(values) == 1 and _valid_content_id(values[0]) else False


def _selected_product(nodes, content_id, card_class, platform):
    selected = []
    for node in nodes:
        ids = [_product_link_id(anchor.get("href", ""), platform)
               for anchor in node.xpath(".//a[@href]") if _nearest_class(anchor, card_class) is node]
        if content_id in ids:
            if False in ids or {value for value in ids if value is not None} != {content_id}:
                return None
            selected.append(node)
    return selected[0] if len(selected) == 1 else None


def _detail_identity(doc, content_id):
    references = doc.xpath("//input[@name='book_num']/@value")
    return bool(references) and all(value == content_id for value in references)


def _bookcube_counts(block):
    result = {}
    for item in block.xpath("./li"):
        text = re.sub(r"\s+", "", "".join(item.itertext()))
        if text.startswith("대출"):
            match = re.fullmatch(r"대출([0-9,]+)/([0-9,]+)", text)
            if not match or "loaned" in result:
                return None
            result["loaned"] = _explicit_count(match.group(1))
            result["total"] = _explicit_count(match.group(2))
        elif text.startswith("예약"):
            match = re.fullmatch(r"예약([0-9,]+)", text)
            if not match or "reserved" in result:
                return None
            result["reserved"] = _explicit_count(match.group(1))
    return result if set(result) == {"loaned", "total", "reserved"} and None not in result.values() else None


def parse_bookcube_status(html: str, content_id: str):
    if not html or not _valid_content_id(content_id):
        return None
    try:
        doc = _html_doc(html)
        # The same book is also rendered in #grid_list without status counts.
        nodes = [node for node in _class_nodes(doc, "li", "item")
                 if any(parent.tag == "ul" and parent.get("id") == "detail_list" for parent in node.iterancestors())]
        book = _selected_product(nodes, content_id, "item", "bookcube")
        if book is None:
            return None
        blocks = [node for node in _class_nodes(book, "ul", "i2") if _nearest_class(node, "item") is book]
        return _bookcube_counts(blocks[0]) if len(blocks) == 1 else None
    except (ValueError, TypeError, lxml_html.etree.ParserError):
        return None


def parse_bookcube_detail_status(html: str, content_id: str = ""):
    if not html or not _valid_content_id(content_id):
        return None
    try:
        doc = _html_doc(html)
        books = _class_nodes(doc, "div", "book_view")
        if len(books) != 1 or not _detail_identity(doc, content_id):
            return None
        book = books[0]
        blocks = [node for node in _class_nodes(book, "ul", "state")
                  if _nearest_class(node, "book_view") is book and _nearest_class(node, "item") is None]
        return _bookcube_counts(blocks[0]) if len(blocks) == 1 else None
    except (ValueError, TypeError, lxml_html.etree.ParserError):
        return None


def _gangnam_counts(blocks):
    statuses = []
    keys = {"보유": "owned", "대출": "loaned", "예약": "reserved"}
    for block in blocks:
        counts = {}
        for node in block.xpath(".//span"):
            label = (node.text or "").strip()
            if label not in keys:
                continue
            key = keys[label]
            numbers = node.xpath("./strong")
            if key in counts or len(numbers) != 1:
                return None
            value = _explicit_count("".join(numbers[0].itertext()))
            if value is None or re.sub(r"\s+", "", "".join(node.itertext())) != label + re.sub(r"\s+", "", "".join(numbers[0].itertext())):
                return None
            counts[key] = value
        if counts:
            if set(counts) != set(keys.values()):
                return None
            statuses.append(counts)
    return statuses[0] if len(statuses) == 1 else None


def parse_gangnam_status(html: str, content_id: str):
    if not html or not _valid_content_id(content_id):
        return None
    try:
        doc = _html_doc(html)
        nodes = [node for node in _class_nodes(doc, "div", "book")
                 if any(_has_class(child, "list_info") for child in node)]
        book = _selected_product(nodes, content_id, "book", "gangnam")
        if book is None:
            return None
        blocks = [node for node in _class_nodes(book, "div", "current") if _nearest_class(node, "book") is book]
        return _gangnam_counts(blocks)
    except (ValueError, TypeError, lxml_html.etree.ParserError):
        return None


def parse_gangnam_detail_status(html: str, content_id: str = ""):
    if not html or not _valid_content_id(content_id):
        return None
    try:
        doc = _html_doc(html)
        books = _class_nodes(doc, "div", "book_warp")
        if len(books) != 1 or not _detail_identity(doc, content_id):
            return None
        book = books[0]
        blocks = [node for node in _class_nodes(book, "div", "current")
                  if _nearest_class(node, "book_warp") is book and _nearest_class(node, "book") is None]
        return _gangnam_counts(blocks)
    except (ValueError, TypeError, lxml_html.etree.ParserError):
        return None


def parse_yes24_status(html: str, goods_id: str = "", operation: str = ""):
    """Read explicit counts only after identifying exactly one requested book.

    A stat fragment alone cannot establish which book it belongs to. Keep the
    detail's return URL or the list book's link when calling this parser.
    """
    if not html or not isinstance(goods_id, str) or not re.fullmatch(r"[0-9]{1,32}", goods_id):
        return None

    def has_class(node, value):
        return value in (node.get("class") or "").split()

    def nearest(node, value):
        return next((parent for parent in node.iterancestors() if has_class(parent, value)), None)

    def matches_detail(value):
        parsed = urlparse(value)
        return (parsed.path in ("/ebook/detail", "/ebook/detail/")
                and parse_qs(parsed.query).get("goods_id") == [goods_id])

    try:
        doc = lxml_html.fromstring(html, parser=lxml_html.HTMLParser(remove_comments=True))
        views = doc.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' ebook-view ')]")
        mode = operation or ("yes24_detail" if views else "yes24_list")
        if mode == "yes24_detail":
            references = doc.xpath("//input[@name='return_url']/@value")
            if len(views) != 1 or not references or not all(matches_detail(value) for value in references):
                return None
            book = views[0]
            stats = [node for node in book.xpath(".//div")
                     if has_class(node, "stat") and nearest(node, "ebook-view") is book
                     and nearest(node, "bx") is None]
        elif mode == "yes24_list":
            books = doc.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' ebook-list ')]"
                              "//div[contains(concat(' ',normalize-space(@class),' '),' bx ')]")
            selected = [book for book in books if any(
                matches_detail(anchor.get("href", "")) and nearest(anchor, "bx") is book
                for anchor in book.xpath(".//a[@href]"))]
            if len(selected) != 1:
                return None
            book = selected[0]
            stats = [node for node in book.xpath(".//div")
                     if has_class(node, "stat") and nearest(node, "bx") is book]
        else:
            return None
        if len(stats) != 1:
            return None
        counts = {}
        keys = {"보유": "owned", "대출": "loaned", "예약": "reserved"}
        for item in stats[0].xpath(".//li"):
            numbers = item.xpath(".//strong")
            if len(numbers) != 1:
                continue
            number = "".join(numbers[0].itertext())
            if not re.fullmatch(r"[0-9]+", number):
                continue
            label = re.sub(r"\s+", "", "".join(item.itertext()).partition(number)[0])
            key = keys.get(label)
            if key:
                if key in counts:
                    return None
                counts[key] = int(number)
        return counts if set(counts) == set(keys.values()) else None
    except (ValueError, TypeError, lxml_html.etree.ParserError):
        return None


def _contents_status(data, content_id):
    if not isinstance(data, dict) or not _valid_content_id(content_id):
        return None
    contents = data.get("Contents")
    records = contents if isinstance(contents, list) else [contents] if isinstance(contents, dict) else []
    selected = [item for item in records if isinstance(item, dict) and item.get("contentsKey") == content_id]
    if len(selected) != 1:
        return None
    keys = {"currentLoanCount": "loaned", "contentsCopys": "total", "currentResvCount": "reserved"}
    result = {target: _explicit_count(selected[0].get(source)) for source, target in keys.items()}
    return result if None not in result.values() else None


def parse_seoul_status(data: dict, content_id: str = ""):
    return _contents_status(data, content_id)


def parse_sen_status(data: dict, content_id: str = ""):
    return _contents_status(data, content_id)


def parse_sen_xml_status(xml: str, content_id: str = ""):
    if not xml or not _valid_content_id(content_id):
        return None
    try:
        parser = lxml_html.etree.XMLParser(resolve_entities=False, no_network=True)
        doc = lxml_html.etree.fromstring(xml.encode("utf-8"), parser=parser)
        if doc.tag != "Map" or doc.getroottree().docinfo.doctype:
            return None
        selected = []
        for record in doc.findall("Contents"):
            ids = record.findall("contentsKey")
            if any(node.text == content_id for node in ids) and len(ids) != 1:
                return None
            if len(ids) == 1 and len(ids[0]) == 0 and ids[0].text == content_id:
                selected.append(record)
        if len(selected) != 1:
            return None
        result = {}
        for source, target in (("currentLoanCount", "loaned"), ("contentsCopys", "total"), ("currentResvCount", "reserved")):
            nodes = selected[0].findall(source)
            if len(nodes) != 1 or len(nodes[0]) != 0:
                return None
            result[target] = _explicit_count(nodes[0].text)
        return result if None not in result.values() else None
    except (ValueError, TypeError, lxml_html.etree.XMLSyntaxError):
        return None


def parse_eunpyeong_status(data: dict):
    if not isinstance(data, dict):
        return None
    contents = data.get("Contents")
    if isinstance(contents, list) and contents:
        contents = contents[0]
    source = contents if isinstance(contents, dict) else data.get("data") if isinstance(data.get("data"), dict) else data
    if isinstance(source, dict):
        has_status_fields = any(
            key in source
            for key in (
                "ContentsCopys",
                "Copys",
                "CurrentLoanCount",
                "ContentLoanCount",
                "CurrentResvCount",
                "ContentResevCount",
                "copys",
                "loanCnt",
                "reserveCnt",
            )
        )
        if not has_status_fields:
            return None
        total = _to_int(source.get("ContentsCopys") or source.get("Copys") or source.get("copys"))
        loaned = _to_int(source.get("CurrentLoanCount") or source.get("ContentLoanCount") or source.get("loanCnt"))
        reserved = _to_int(source.get("CurrentResvCount") or source.get("ContentResevCount") or source.get("reserveCnt"))
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
