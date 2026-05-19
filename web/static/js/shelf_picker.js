(function () {
    const shelf = window.SoulibShelf;
    let activeBook = null;
    let activeKey = "";

    const ICONS = {
        plus: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>',
        check: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"></path></svg>',
        close: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12"></path><path d="M18 6 6 18"></path></svg>',
        bookmark: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z"></path></svg>',
        bookmarkSaved: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M6.75 3h10.5A2.75 2.75 0 0 1 20 5.75v14.1a1.1 1.1 0 0 1-1.67.94L12 16.96l-6.33 3.83A1.1 1.1 0 0 1 4 19.85V5.75A2.75 2.75 0 0 1 6.75 3Z"></path></svg>',
    };

    function cleanText(value) {
        return String(value || "").trim();
    }

    function escapeHtml(value) {
        return String(value || "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function escapeAttr(value) {
        return escapeHtml(value).replaceAll("`", "&#96;");
    }

    function ensureSheet() {
        if (document.getElementById("shelf-picker-sheet")) return;
        document.body.insertAdjacentHTML("beforeend", `
            <div class="shelf-picker-overlay" id="shelf-picker-overlay" hidden></div>
            <section class="shelf-picker-sheet" id="shelf-picker-sheet" role="dialog" aria-modal="true" aria-labelledby="shelf-picker-title" hidden>
                <div class="shelf-picker-head">
                    <h2 id="shelf-picker-title">내 서재에 담기</h2>
                    <button class="shelf-picker-close" type="button" data-shelf-picker-close aria-label="닫기">${ICONS.close}</button>
                </div>
                <div class="shelf-picker-book" id="shelf-picker-book"></div>
                <div class="shelf-picker-lists" id="shelf-picker-lists"></div>
                <form class="shelf-picker-form" id="shelf-picker-form">
                    <label class="sr-only" for="shelf-picker-new-name">새 서재 이름</label>
                    <input id="shelf-picker-new-name" type="text" maxlength="80" placeholder="새 서재 이름">
                    <button type="submit" aria-label="새 서재 만들고 담기">${ICONS.plus}</button>
                </form>
                <a class="shelf-picker-link" href="/my-shelf">내 서재 열기</a>
            </section>
        `);
        document.getElementById("shelf-picker-overlay").addEventListener("click", close);
        document.querySelector("[data-shelf-picker-close]").addEventListener("click", close);
        document.getElementById("shelf-picker-lists").addEventListener("change", event => {
            const input = event.target.closest("[data-shelf-picker-list]");
            if (!input || !activeBook || !activeKey) return;
            if (input.checked) {
                shelf.add(activeBook, input.value);
            } else {
                shelf.removeFromList(activeKey, input.value);
            }
            render();
        });
        document.getElementById("shelf-picker-form").addEventListener("submit", event => {
            event.preventDefault();
            const input = document.getElementById("shelf-picker-new-name");
            const list = shelf.createList(input.value);
            if (!list) return;
            shelf.add(activeBook, list.id);
            input.value = "";
            render();
        });
    }

    function open(book) {
        if (!shelf || !book) return;
        activeBook = book;
        activeKey = shelf.keyFor(book);
        ensureSheet();
        render();
        document.getElementById("shelf-picker-overlay").hidden = false;
        document.getElementById("shelf-picker-sheet").hidden = false;
        document.body.classList.add("shelf-picker-open");
    }

    function close() {
        const overlay = document.getElementById("shelf-picker-overlay");
        const sheet = document.getElementById("shelf-picker-sheet");
        if (overlay) overlay.hidden = true;
        if (sheet) sheet.hidden = true;
        document.body.classList.remove("shelf-picker-open");
    }

    function render() {
        if (!activeBook || !activeKey) return;
        const bookEl = document.getElementById("shelf-picker-book");
        const listsEl = document.getElementById("shelf-picker-lists");
        if (!bookEl || !listsEl) return;

        const meta = [activeBook.author, activeBook.publisher].filter(Boolean).join(" · ");
        bookEl.innerHTML = `
            <div class="shelf-picker-book-title">${escapeHtml(activeBook.title || "")}</div>
            ${meta ? `<div class="shelf-picker-book-meta">${escapeHtml(meta)}</div>` : ""}
        `;

        listsEl.innerHTML = shelf.listAll().map(list => {
            const checked = shelf.has(activeKey, list.id);
            const count = (list.book_keys || []).length;
            return `
                <label class="shelf-picker-list">
                    <input type="checkbox" data-shelf-picker-list value="${escapeAttr(list.id)}" ${checked ? "checked" : ""}>
                    <span class="shelf-picker-list-main">
                        <strong>${escapeHtml(list.name)}</strong>
                        <small>${count.toLocaleString()}권</small>
                    </span>
                    <span class="shelf-picker-check" aria-hidden="true">${ICONS.check}</span>
                </label>
            `;
        }).join("");
    }

    function isSaved(book) {
        return !!(shelf && book && shelf.has(shelf.keyFor(book)));
    }

    function syncTrigger(button, book) {
        if (!button || !shelf || !book) return;
        const saved = isSaved(book);
        const title = cleanText(book.title) || "도서";
        button.innerHTML = saved ? ICONS.bookmarkSaved : ICONS.bookmark;
        button.classList.toggle("is-saved", saved);
        button.setAttribute("aria-label", saved ? `${title} 내 서재에 담김` : `${title} 내 서재에 담기`);
        button.title = saved ? "내 서재에 담김" : "내 서재에 담기";
    }

    window.SoulibShelfPicker = {
        open,
        close,
        isSaved,
        syncTrigger,
    };
})();
