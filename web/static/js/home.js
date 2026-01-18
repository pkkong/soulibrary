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
    const params = new URLSearchParams();
    params.set("ids", ids.join(","));
    const res = await fetch(`/api/books?${params.toString()}`);
    const data = await res.json();
    if (!Array.isArray(data)) return [];
    const byId = new Map(data.map(b => [String(b.book_id || b.id), b]));
    return ids.map(id => byId.get(String(id))).filter(Boolean);
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

async function initCurations() {
    try {
        const chanhoIds = [261, 7939, 31037, 439973, 275025];
        const chanho = await fetchBooksByIds(chanhoIds);
        const bitcoinIds = [29621, 293944, 231444, 234760, 303558, 182651];
        const bitcoin = await fetchBooksByIds(bitcoinIds);

        const cafeIds = [1163, 1653, 3900, 2361, 62991, 165705, 269836, 239293];
        const cafeBooks = await fetchBooksByIds(cafeIds);

        const jeongyujeongIds = [311288, 458653, 456403, 459032, 460178];
        const jeongyujeong = await fetchBooksByIds(jeongyujeongIds);

        const jeonghaeyeonIds = [1749, 2666, 2792, 4727, 9221];
        const jeonghaeyeon = await fetchBooksByIds(jeonghaeyeonIds);

        renderInto("curation-higashino", cafeBooks, renderHeroCoverCard);
        const heroTrack = document.getElementById("curation-higashino");
        setupInfiniteCenteredCarousel(heroTrack);
        renderInto("curation-bitcoin", bitcoin, renderRankedCard);
        renderInto("curation-chanho", chanho, renderCoverCard);
        renderInto("curation-jeongyujeong", jeongyujeong, renderCoverCard);
        renderInto("curation-jeonghaeyeon", jeonghaeyeon, renderCoverCard);

        document.querySelectorAll(".curation-track").forEach(enableDragScroll);
    } catch (e) {
        console.error(e);
    }
}

document.addEventListener("DOMContentLoaded", initCurations);
