function escHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function bookHref(bookId) {
    if (!bookId) return "#";
    return `/book/${encodeURIComponent(bookId)}`;
}

function renderInlineCard(book) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const author = escHtml(book.author || "");
    const img = book.image_url
        ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="">`
        : `<div class="curation-noimg">표지 없음</div>`;
    return `
        <a class="curation-inline-link" href="${bookHref(id)}">
            <div class="curation-feature-cover">${img}</div>
            <div class="curation-inline-meta">
                <div class="curation-feature-title">${title}</div>
                ${author ? `<div class="curation-feature-author">${author}</div>` : ""}
            </div>
        </a>
    `;
}

function renderCompactCard(book) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const author = escHtml(book.author || "");
    const img = book.image_url
        ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="">`
        : `<div class="curation-noimg">표지 없음</div>`;
    return `
        <a class="curation-compact-card" href="${bookHref(id)}">
            <div class="curation-compact-thumb">${img}</div>
            <div class="curation-compact-title">${title}</div>
            ${author ? `<div class="curation-compact-author">${author}</div>` : ""}
        </a>
    `;
}

function injectInlineBooks(container, books, alignedBooks) {
    if (!container || !books || !books.length) return;
    const blocks = Array.from(container.querySelectorAll(".curation-book-block"));
    if (blocks.length) {
        const source = Array.isArray(alignedBooks) && alignedBooks.length ? alignedBooks : books;
        const count = Math.min(blocks.length, source.length);
        for (let i = 0; i < count; i += 1) {
            const book = source[i];
            if (!book) continue;
            if (blocks[i].querySelector(".curation-inline-card")) continue;
            const wrap = document.createElement("div");
            wrap.className = "curation-inline-card curation-feature-card";
            wrap.innerHTML = renderInlineCard(book);
            const titleNode = blocks[i].querySelector("h4, h3");
            if (titleNode) {
                titleNode.insertAdjacentElement("afterend", wrap);
            } else {
                blocks[i].appendChild(wrap);
            }
        }
        return;
    }

    const list = container.querySelector("ol");
    if (list) {
        const items = Array.from(list.querySelectorAll("li"));
        const source = Array.isArray(alignedBooks) && alignedBooks.length ? alignedBooks : books;
        const count = Math.min(items.length, source.length);
        for (let i = 0; i < count; i += 1) {
            const book = source[i];
            if (!book) continue;
            const wrap = document.createElement("div");
            wrap.className = "curation-inline-card curation-feature-card";
            wrap.innerHTML = renderInlineCard(book);
            items[i].insertAdjacentElement("afterend", wrap);
        }
        return;
    }
    const paragraphs = Array.from(container.querySelectorAll("p"));
    if (!paragraphs.length) return;
    const source = Array.isArray(alignedBooks) && alignedBooks.length ? alignedBooks : books;
    const usable = source.filter(Boolean);
    if (!usable.length) return;
    const step = Math.max(1, Math.floor(paragraphs.length / Math.min(usable.length, 3)));
    let idx = 0;
    for (let i = step - 1; i < paragraphs.length && idx < usable.length; i += step) {
        const wrap = document.createElement("div");
        wrap.className = "curation-inline-card curation-feature-card";
        wrap.innerHTML = renderInlineCard(usable[idx]);
        paragraphs[i].insertAdjacentElement("afterend", wrap);
        idx += 1;
    }
}

async function fetchBooksByIds(ids) {
    if (!ids || !ids.length) return [];
    const params = new URLSearchParams();
    params.set("ids", ids.join(","));
    const res = await fetch(`/api/books?${params.toString()}`);
    const data = await res.json();
    if (!Array.isArray(data)) return [];
    const byId = new Map(data.map((b) => [String(b.book_id || b.id), b]));
    return ids.map((id) => byId.get(String(id))).filter(Boolean);
}

function normalizeText(value) {
    return String(value || "").toLowerCase().replace(/\s+/g, "");
}

function normalizeStrictText(value) {
    return String(value || "")
        .toLowerCase()
        .replace(/[^0-9a-z\uac00-\ud7a3]/g, "");
}

function scoreBookMatch(entry, item) {
    const targetTitle = normalizeStrictText(entry.title);
    const itemTitle = normalizeStrictText(item.title);
    const targetTitleLoose = normalizeText(entry.title);
    const itemTitleLoose = normalizeText(item.title);
    const targetAuthor = normalizeStrictText(entry.author);
    const itemAuthor = normalizeStrictText(item.author);

    let titleScore = 0;
    if (targetTitle && itemTitle) {
        if (itemTitle === targetTitle) {
            titleScore = 100;
        } else if (itemTitle.startsWith(targetTitle) || targetTitle.startsWith(itemTitle)) {
            titleScore = 70;
        } else if (
            itemTitleLoose.includes(targetTitleLoose) ||
            targetTitleLoose.includes(itemTitleLoose)
        ) {
            titleScore = 40;
        }
    }

    let authorScore = 0;
    if (targetAuthor && itemAuthor) {
        if (itemAuthor === targetAuthor) {
            authorScore = 40;
        } else if (itemAuthor.includes(targetAuthor) || targetAuthor.includes(itemAuthor)) {
            authorScore = 20;
        }
    }

    return {
        titleScore,
        authorScore,
        total: titleScore + authorScore,
    };
}

async function fetchBookByTitle(entry) {
    const title = String(entry.title || "").trim();
    if (!title) return null;
    const params = new URLSearchParams();
    params.set("query", title);
    params.set("field", "title");
    params.set("limit", "20");
    params.set("offset", "0");
    const res = await fetch(`/api/search?${params.toString()}`);
    const data = await res.json();
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) return null;

    const scored = items
        .map((item) => ({ item, score: scoreBookMatch(entry, item) }))
        .sort((a, b) => b.score.total - a.score.total);

    const best = scored[0];
    if (!best) return null;

    const hasAuthor = normalizeStrictText(entry.author).length > 0;
    if (best.score.titleScore < 70) return null;
    if (hasAuthor && best.score.authorScore < 20) return null;
    return best.item;
}

async function fetchBooksByEntries(entries) {
    const tasks = entries.map((entry) => fetchBookByTitle(entry));
    return Promise.all(tasks);
}

function removeLegacySearchLinks(container) {
    if (!container) return;
    const links = Array.from(container.querySelectorAll('a[href^="/search?q="]'));
    links.forEach((link) => {
        const text = (link.textContent || "").trim();
        if (text && text !== "우리 서비스에서 이 책 보기") return;
        const parent = link.closest("p");
        if (parent && parent.querySelectorAll("a").length === 1) {
            parent.remove();
        } else {
            link.remove();
        }
    });
}

function removeSourceLinks(container) {
    if (!container) return;
    const links = Array.from(container.querySelectorAll("a"));
    links.forEach((link) => {
        const text = (link.textContent || "").trim();
        if (!/^출처\s*\d*$/.test(text)) return;
        const parent = link.closest("p");
        if (parent && parent.querySelectorAll("a").length === 1) {
            parent.remove();
        } else {
            link.remove();
        }
    });
}

function removeLegacyHeading(container) {
    if (!container) return;
    const headings = Array.from(container.querySelectorAll("h2, h3, h4"));
    headings.forEach((node) => {
        const text = (node.textContent || "").replace(/\s+/g, "");
        if (text === "추천도서와이유") node.remove();
    });
}

function addIntroOutroDividers(container) {
    if (!container) return;
    const blocks = Array.from(container.querySelectorAll(".curation-book-block"));
    if (!blocks.length) return;

    const firstBlock = blocks[0];
    const lastBlock = blocks[blocks.length - 1];

    if (firstBlock.previousElementSibling && !firstBlock.previousElementSibling.classList.contains("curation-divider")) {
        const dividerTop = document.createElement("hr");
        dividerTop.className = "curation-divider";
        firstBlock.insertAdjacentElement("beforebegin", dividerTop);
    }

    let firstOutro = lastBlock.nextElementSibling;
    while (firstOutro && firstOutro.classList && firstOutro.classList.contains("curation-divider")) {
        firstOutro = firstOutro.nextElementSibling;
    }
    if (firstOutro && !firstOutro.previousElementSibling.classList.contains("curation-divider")) {
        const dividerBottom = document.createElement("hr");
        dividerBottom.className = "curation-divider";
        firstOutro.insertAdjacentElement("beforebegin", dividerBottom);
    }
}

async function initCurationDetail() {
    const container = document.getElementById("curation-books");
    if (!container) return;
    const curation = window.__CURATION__ || {};
    try {
        let books = [];
        let alignedBooks = [];
        const ids = Array.isArray(curation.book_ids) ? curation.book_ids : [];
        if (ids.length) {
            books = await fetchBooksByIds(ids);
            alignedBooks = books;
        } else if (Array.isArray(curation.books) && curation.books.length) {
            alignedBooks = await fetchBooksByEntries(curation.books);
            books = alignedBooks.filter(Boolean);
        }
        if (!books.length) {
            container.innerHTML = `<div class="curation-empty">표시할 책이 없습니다.</div>`;
        } else {
            container.innerHTML = books.map(renderCompactCard).join("");
        }
        const content = document.getElementById("curation-article-content");
        if (content) {
            removeLegacySearchLinks(content);
            removeSourceLinks(content);
            removeLegacyHeading(content);
            injectInlineBooks(content, books, alignedBooks);
            addIntroOutroDividers(content);
        }
    } catch (e) {
        console.error(e);
        container.innerHTML = `<div class="curation-empty">데이터를 불러오지 못했습니다.</div>`;
    }
}

document.addEventListener("DOMContentLoaded", initCurationDetail);
