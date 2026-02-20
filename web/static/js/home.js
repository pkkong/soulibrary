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

function getUniqueLibraryCount(book) {
    const libs = Array.isArray(book.libraries) ? book.libraries : [];
    const seen = new Set();
    libs.forEach(l => {
        const key = l && (l.code || l.name || l.short);
        if (!key) return;
        seen.add(key);
    });
    return seen.size;
}

function renderCoverCard(book) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const img = book.image_url ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="" draggable="false">` : `<div class="curation-noimg">이미지 없음</div>`;
    return `
        <a class="curation-card curation-card-basic" href="${bookHref(id)}">
            <div class="curation-cover">${img}</div>
            <div class="curation-cover-title">${title}</div>
        </a>
    `;
}

function renderHeroCoverCard(book) {
    const id = book.book_id || book.id;
    const imageUrl = book.image_url ? escHtml(book.image_url) : "";

    const bgStyle = imageUrl ? `style="--bg:url('${imageUrl}')"` : "";
    const coverHtml = imageUrl
        ? `<img src="${imageUrl}" loading="lazy" alt="" draggable="false">`
        : `<div class="curation-noimg">이미지 없음</div>`;

    return `
        <a class="curation-card curation-card-hero" href="${bookHref(id)}">
            <div class="curation-hero" ${bgStyle}>
                <div class="curation-hero-bg"></div>
                <div class="curation-hero-cover">${coverHtml}</div>
            </div>
        </a>
    `;
}

function renderRankedCard(book, index) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const author = escHtml(book.author);
    const img = book.image_url ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="" draggable="false">` : `<div class="curation-noimg">이미지 없음</div>`;
    return `
        <a class="curation-card curation-card-ranked" href="${bookHref(id)}">
            <div class="curation-rank">${index + 1}</div>
            <div class="curation-thumb">${img}</div>
            <div class="curation-text">
                <div class="curation-book-title">${title}</div>
                <div class="curation-book-sub">${author}</div>
            </div>
        </a>
    `;
}

function renderTiltCard(book) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const author = escHtml(book.author);
    const img = book.image_url
        ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="" draggable="false">`
        : `<div class="curation-noimg">이미지 없음</div>`;
    return `
        <a class="curation-card curation-card-tilt" href="${bookHref(id)}">
            <div class="curation-tilt-stage">
                <div class="curation-tilt-cover">${img}</div>
            </div>
            <div class="curation-cover-title">${title}</div>
            <div class="curation-book-sub">${author}</div>
        </a>
    `;
}

function renderEditorialCard(book) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const author = escHtml(book.author);
    const img = book.image_url
        ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="" draggable="false">`
        : `<div class="curation-noimg">이미지 없음</div>`;
    return `
        <a class="curation-card curation-card-editorial" href="${bookHref(id)}">
            <div class="curation-editorial-cover">${img}</div>
            <div class="curation-editorial-title">${title}</div>
            <div class="curation-editorial-sub">${author}</div>
        </a>
    `;
}

function renderCompactCard(book) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const author = escHtml(book.author);
    const img = book.image_url
        ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="" draggable="false">`
        : `<div class="curation-noimg">이미지 없음</div>`;
    return `
        <a class="curation-card curation-card-compact" href="${bookHref(id)}">
            <div class="curation-compact-cover">${img}</div>
            <div class="curation-compact-meta">
                <div class="curation-book-title">${title}</div>
                <div class="curation-book-sub">${author}</div>
            </div>
        </a>
    `;
}

function renderNewsCard(book, index) {
    const id = book.book_id || book.id;
    const title = escHtml(book.title);
    const author = escHtml(book.author);
    const img = book.image_url
        ? `<img src="${escHtml(book.image_url)}" loading="lazy" alt="" draggable="false">`
        : `<div class="curation-noimg">이미지 없음</div>`;
    const palette = ["#f2dede", "#e9e5d8", "#dfe8f4", "#e4efe2", "#ede2ef"];
    const bg = palette[index % palette.length];
    return `
        <a class="curation-card curation-card-news" href="${bookHref(id)}" style="--news-bg:${bg}">
            <div class="curation-news-copy">
                <div class="curation-news-kicker">오늘의 선택</div>
                <div class="curation-news-title">${title}</div>
                <div class="curation-news-sub">${author || "지금 읽어보기"}</div>
            </div>
            <div class="curation-news-cover">${img}</div>
        </a>
    `;
}

async function fetchTopByAuthor(authorName, limit = 5) {
    const params = new URLSearchParams();
    params.set("query", authorName);
    params.set("field", "author");
    params.set("limit", String(Math.max(10, limit)));
    params.set("offset", "0");
    const res = await fetch(`/api/search?${params.toString()}`);
    const data = await res.json();
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) return [];
    items.sort((a, b) => getUniqueLibraryCount(b) - getUniqueLibraryCount(a));
    return items.slice(0, limit);
}

async function fetchBooksByIds(ids) {
    if (!Array.isArray(ids) || !ids.length) return [];
    const params = new URLSearchParams();
    params.set("ids", ids.join(","));
    const res = await fetch(`/api/books?${params.toString()}`);
    const data = await res.json();
    if (!Array.isArray(data)) return [];
    const byId = new Map(data.map(b => [String(b.book_id || b.id), b]));
    return ids.map(id => byId.get(String(id))).filter(Boolean);
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
    if (!Array.isArray(entries) || !entries.length) return [];
    const tasks = entries.map((entry) => fetchBookByTitle(entry));
    const result = await Promise.all(tasks);
    return result.filter(Boolean);
}

function renderInto(containerId, books, renderer) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!books.length) {
        el.innerHTML = `<div class="curation-empty">표시할 책이 없습니다.</div>`;
        return;
    }
    el.innerHTML = books.map(renderer).join("");
}

function enableDragScroll(trackEl) {
    if (!trackEl) return;

    let isDown = false;
    let startX = 0;
    let startScrollLeft = 0;
    let dragged = false;
    let suppressClickUntil = 0;

    function startDrag(clientX) {
        isDown = true;
        dragged = false;
        startX = clientX;
        startScrollLeft = trackEl.scrollLeft;
        trackEl.classList.add("is-dragging");
    }

    function updateDrag(clientX, event) {
        if (!isDown) return;
        const dx = clientX - startX;
        if (!dragged && Math.abs(dx) > 4) dragged = true;
        if (dragged) {
            event?.preventDefault();
            trackEl.scrollLeft = startScrollLeft - dx;
        }
    }

    function endDrag() {
        if (!isDown) return;
        isDown = false;
        trackEl.classList.remove("is-dragging");
        if (dragged) suppressClickUntil = Date.now() + 250;
    }

    function onMouseDown(e) {
        if (e.button !== 0) return;
        startDrag(e.clientX);
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
        document.addEventListener("mouseleave", onMouseUp);
    }

    function onMouseMove(e) {
        updateDrag(e.clientX, e);
    }

    function onMouseUp() {
        endDrag();
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.removeEventListener("mouseleave", onMouseUp);
    }

    trackEl.addEventListener("mousedown", onMouseDown);
    trackEl.addEventListener("dragstart", (e) => e.preventDefault());
    trackEl.addEventListener(
        "click",
        (e) => {
            if (Date.now() < suppressClickUntil) {
                e.preventDefault();
                e.stopPropagation();
            }
        },
        true
    );
}

function setupInfiniteCenteredCarousel(trackEl) {
    if (!trackEl) return;
    const originals = Array.from(trackEl.querySelectorAll(".curation-card"));
    if (originals.length < 2) return;

    const fragHead = document.createDocumentFragment();
    const fragTail = document.createDocumentFragment();
    originals.forEach((node) => fragTail.appendChild(node.cloneNode(true)));
    originals.forEach((node) => fragHead.appendChild(node.cloneNode(true)));

    trackEl.prepend(fragHead);
    trackEl.appendChild(fragTail);

    const all = () => Array.from(trackEl.querySelectorAll(".curation-card"));
    const originalStartIndex = originals.length;
    const originalCenterIndex = originalStartIndex + Math.floor(originals.length / 2);

    function updateHeroPadding() {
        const cards = all();
        const centerCard = cards[originalCenterIndex] || cards[originalStartIndex];
        if (!centerCard) return;
        const pad = Math.max(0, (trackEl.clientWidth - centerCard.clientWidth) / 2);
        trackEl.style.paddingLeft = `${pad}px`;
        trackEl.style.paddingRight = `${pad}px`;
        trackEl.style.scrollPaddingLeft = `${pad}px`;
        trackEl.style.scrollPaddingRight = `${pad}px`;
    }

    function jumpToOriginalBand() {
        const cards = all();
        const startCard = cards[originalCenterIndex] || cards[originalStartIndex];
        if (startCard) trackEl.scrollLeft = startCard.offsetLeft - (trackEl.clientWidth - startCard.clientWidth) / 2;
    }

    function getBandWidth() {
        const cards = all();
        const first = cards[originalStartIndex];
        const last = cards[originalStartIndex + originals.length - 1];
        if (!first || !last) return 0;
        return (last.offsetLeft + last.offsetWidth) - first.offsetLeft;
    }

    let bandWidth = 0;
    function refreshBand() {
        updateHeroPadding();
        bandWidth = getBandWidth();
    }

    function applyScale() {
        const cards = all();
        cards.forEach((card) => {
            card.style.transform = "scale(1)";
            card.style.opacity = "1";
        });
    }

    function handleLoop() {
        if (!bandWidth) return;
        const cards = all();
        const firstBand = cards[originalStartIndex];
        if (!firstBand) return;
        const bandLeft = firstBand.offsetLeft;
        const leftEdge = bandLeft - bandWidth * 0.35;
        const rightEdge = bandLeft + bandWidth * 1.35;

        if (trackEl.scrollLeft < leftEdge) {
            trackEl.scrollLeft += bandWidth;
        } else if (trackEl.scrollLeft > rightEdge) {
            trackEl.scrollLeft -= bandWidth;
        }
    }

    let raf = 0;
    function onScroll() {
        if (raf) return;
        raf = requestAnimationFrame(() => {
            raf = 0;
            handleLoop();
            applyScale();
        });
    }

    trackEl.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", () => {
        refreshBand();
        jumpToOriginalBand();
        applyScale();
    });

    function setAligning(state) {
        if (state) trackEl.classList.add("is-aligning");
        else trackEl.classList.remove("is-aligning");
    }

    function initialAlign() {
        setAligning(true);
        refreshBand();
        jumpToOriginalBand();
        applyScale();
        setTimeout(() => setAligning(false), 60);
    }

    // after layout & images settle
    requestAnimationFrame(() => {
        initialAlign();
        setTimeout(initialAlign, 120);
    });

    const imgs = trackEl.querySelectorAll("img");
    if (imgs.length) {
        let pending = imgs.length;
        const done = () => {
            pending -= 1;
            if (pending <= 0) initialAlign();
        };
        imgs.forEach((img) => {
            if (img.complete) {
                done();
            } else {
                img.addEventListener("load", done, { once: true });
                img.addEventListener("error", done, { once: true });
            }
        });
    } else {
        initialAlign();
    }
}

function setupNewsCarousel(trackEl) {
    if (!trackEl) return;
    const cards = Array.from(trackEl.querySelectorAll(".curation-card-news"));
    if (!cards.length) return;

    const wrap = trackEl.parentElement;
    if (!wrap) return;
    const existing = wrap.querySelector(".curation-news-controls");
    if (existing) existing.remove();

    if (cards.length <= 1) return;

    const controls = document.createElement("div");
    controls.className = "curation-news-controls";
    controls.innerHTML = `
        <button type="button" class="curation-news-btn prev" aria-label="이전">‹</button>
        <button type="button" class="curation-news-btn next" aria-label="다음">›</button>
    `;
    wrap.insertBefore(controls, trackEl.nextSibling);

    const prev = controls.querySelector(".prev");
    const next = controls.querySelector(".next");
    let current = 0;
    let ticking = false;

    function scrollToCurrent(smooth = true) {
        const card = cards[current];
        if (!card) return;
        trackEl.scrollTo({
            left: card.offsetLeft - 12,
            behavior: smooth ? "smooth" : "auto",
        });
    }

    function updateButtons() {
        prev.disabled = current <= 0;
        next.disabled = current >= cards.length - 1;
    }

    function syncCurrentFromScroll() {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(() => {
            ticking = false;
            const center = trackEl.scrollLeft + trackEl.clientWidth / 2;
            let nearest = 0;
            let nearestDist = Infinity;
            cards.forEach((card, idx) => {
                const cardCenter = card.offsetLeft + card.clientWidth / 2;
                const dist = Math.abs(center - cardCenter);
                if (dist < nearestDist) {
                    nearestDist = dist;
                    nearest = idx;
                }
            });
            current = nearest;
            updateButtons();
        });
    }

    prev.addEventListener("click", () => {
        current = Math.max(0, current - 1);
        updateButtons();
        scrollToCurrent(true);
    });

    next.addEventListener("click", () => {
        current = Math.min(cards.length - 1, current + 1);
        updateButtons();
        scrollToCurrent(true);
    });

    trackEl.addEventListener("scroll", syncCurrentFromScroll, { passive: true });
    window.addEventListener("resize", () => {
        scrollToCurrent(false);
        updateButtons();
    });

    scrollToCurrent(false);
    updateButtons();
}

async function initCurations() {
    try {
        const sections = Array.isArray(window.__HOME_CURATIONS__) ? window.__HOME_CURATIONS__ : [];
        if (!sections.length) return;

        for (const section of sections) {
            const trackId = section.section_id;
            if (!trackId) continue;

            let books = [];
            const bookIds = Array.isArray(section.book_ids) ? section.book_ids : [];
            const entries = Array.isArray(section.books) ? section.books : [];
            if (bookIds.length) {
                books = await fetchBooksByIds(bookIds);
            } else if (entries.length) {
                books = await fetchBooksByEntries(entries);
            }

            const style = section.home_style;
            if (style === "hero") {
                renderInto(trackId, books, renderHeroCoverCard);
                setupInfiniteCenteredCarousel(document.getElementById(trackId));
            } else if (style === "ranked") {
                renderInto(trackId, books, renderRankedCard);
            } else if (style === "tilt") {
                renderInto(trackId, books, renderTiltCard);
            } else if (style === "editorial") {
                renderInto(trackId, books, renderEditorialCard);
            } else if (style === "compact") {
                renderInto(trackId, books, renderCompactCard);
            } else if (style === "news") {
                renderInto(trackId, books, renderNewsCard);
                setupNewsCarousel(document.getElementById(trackId));
            } else {
                renderInto(trackId, books, renderCoverCard);
            }
        }

        document.querySelectorAll(".curation-track").forEach(enableDragScroll);
    } catch (e) {
        console.error(e);
    }
}

document.addEventListener("DOMContentLoaded", initCurations);
