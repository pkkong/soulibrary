import os
import re
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from web import db


def normalize_text(value: str) -> str:
    if not value:
        return ""
    text = str(value).lower()
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[\s\[\]\(\){}<>.,/|\\\-_:\;\"'`~!?]", "", text)
    return text


def normalize_title(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"\[.*?\]|\(.*?\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return normalize_text(text)


def normalize_author(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"(지은이|저자|저|역|옮긴이|편|엮음|그림|삽화|해설)", " ", text)
    text = re.sub(r"[:：]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return normalize_text(text)


def normalize_publisher(value: str) -> str:
    if not value:
        return ""
    text = str(value)
    text = re.sub(r"(주식회사|\(주\)|㈜|출판사)$", "", text).strip()
    return normalize_text(text)


def main():
    dry_run = "--dry-run" in sys.argv
    conn = db.get_db()
    try:
        cur = conn.execute("SELECT id, title, author, publisher FROM books")
        rows = cur.fetchall()
        cur.close()
        if dry_run:
            sample = rows[:5]
            for row in sample:
                title_norm = normalize_title(row["title"])
                author_norm = normalize_author(row["author"])
                publisher_norm = normalize_publisher(row["publisher"])
                print(row["id"], title_norm, author_norm, publisher_norm)
            conn.rollback()
            return

        batch = []
        for row in rows:
            batch.append(
                (
                    normalize_title(row["title"]),
                    normalize_author(row["author"]),
                    normalize_publisher(row["publisher"]),
                    row["id"],
                )
            )
        cur = conn._conn.cursor()
        cur.executemany(
            "UPDATE books SET title_norm=%s, author_norm=%s, publisher_norm=%s WHERE id=%s",
            batch,
        )
        conn._conn.commit()
        cur.close()
        print(f"updated {len(batch)} rows")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
