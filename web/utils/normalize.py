import re

def normalize_title(text):
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"\[.*?\]|\(.*?\)", "", text)
    text = re.sub(r"(\d)\s*(권|冊|권수)", r"\1", text)
    text = re.sub(r"[^\w\s]", "", text).strip()
    text = re.sub(r"\s+", "", text)
    return text


def normalize_author(text):
    if not text:
        return ""
    text = str(text)
    text = re.sub(r"[<>\(\)\[\]]", " ", text)
    split_chars = r"[,/|]"
    if re.search(split_chars, text):
        text = re.split(split_chars, text, 1)[0]
    roles = r"(지음|글|그림|그림책|옮김|엮음|편집)"
    text = re.sub(roles, "", text)
    text = re.sub(r"[^\w\s]", "", text).lower().strip()
    text = re.sub(r"\s+", "", text)
    return text


def normalize_search_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower().strip()
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[\s\[\]\(\){}<>.,/|\\\-_:\;\"'`~!?]", "", text)
    return text


def normalize_search_tokens(text: str) -> list[str]:
    if not text:
        return []
    raw = str(text).lower().strip()
    raw = re.sub(r"[\u200b\ufeff]", "", raw)
    parts = re.split(r"[\s\[\]\(\){}<>.,/|\\\-_:\;\"'`~!?]+", raw)
    tokens = []
    for part in parts:
        norm = normalize_search_text(part)
        if norm:
            tokens.append(norm)
    return tokens


def normalize_provider(raw_value):
    mapping = {
        "교보문고": "교보",
        "교보": "교보",
        "kyobo": "교보",
        "교보도서관": "교보",
        "yes24": "YES24",
        "YES24": "YES24",
        "예스24": "YES24",
        "예스이십사": "YES24",
        "예스": "YES24",
        "aladin": "알라딘",
        "알라딘": "알라딘",
    }
    if raw_value:
        key = str(raw_value).strip()
        norm = mapping.get(key) or mapping.get(key.lower())
        return norm or key
    return ""
