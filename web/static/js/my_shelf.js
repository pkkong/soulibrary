const shelfItems = document.getElementById("shelf-items");
const shelfEmpty = document.getElementById("shelf-empty");
const shelfCount = document.getElementById("shelf-count");
const shelfClear = document.getElementById("shelf-clear");
const shelfListCount = document.getElementById("shelf-list-count");
const shelfListTabs = document.getElementById("shelf-list-tabs");
const shelfListTitle = document.getElementById("shelf-list-title");
const shelfListDesc = document.getElementById("shelf-list-desc");
const shelfCreateForm = document.getElementById("shelf-create-form");
const shelfCreateName = document.getElementById("shelf-create-name");
const shelfCreateToggle = document.getElementById("shelf-create-toggle");
const shelfManageToggle = document.getElementById("shelf-manage-toggle");
const shelfManageActions = document.getElementById("shelf-manage-actions");
const shelfRename = document.getElementById("shelf-rename");
const shelfDeleteList = document.getElementById("shelf-delete-list");
const shelfShare = document.getElementById("shelf-share");
const shelfSharePanel = document.getElementById("shelf-share-panel");
const shelfShareUrl = document.getElementById("shelf-share-url");
const shelfCopyShare = document.getElementById("shelf-copy-share");
const shelfShareStatus = document.getElementById("shelf-share-status");
const shelfViewButtons = Array.from(document.querySelectorAll("[data-shelf-view]"));
const shelf = window.SoulibShelf;
const ACTIVE_LIST_KEY = "soulib.myShelf.activeList";
const VIEW_MODE_KEY = "soulib.myShelf.viewMode";
const VIEW_MODES = new Set(["grid3", "grid2", "list"]);
const MIN_COVER_SOURCE_WIDTH = 170;
const ICONS = {
    remove: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><path d="M6 6l12 12"></path><path d="M18 6 6 18"></path></svg>',
};

let activeListId = localStorage.getItem(ACTIVE_LIST_KEY) || "";
let shelfViewMode = localStorage.getItem(VIEW_MODE_KEY) || "grid3";
let manageOpen = false;
if (!VIEW_MODES.has(shelfViewMode)) shelfViewMode = "grid3";

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

function coverCandidateUrls(book) {
    const urls = [];
    function addUrl(value) {
        const url = cleanText(value);
        if (!url || urls.includes(url)) return;
        if (!/^https?:\/\//i.test(url) && !url.startsWith("//")) return;
        urls.push(url.startsWith("//") ? `https:${url}` : url);
    }
    addUrl(book && book.image_url);
    (Array.isArray(book && book.image_candidates) ? book.image_candidates : []).forEach(candidate => {
        addUrl(typeof candidate === "string" ? candidate : candidate && (candidate.url || candidate.image_url));
    });
    return urls;
}

function coverHtml(book, className) {
    const urls = coverCandidateUrls(book);
    if (!urls.length) return `<div class="${className} shelf-no-cover">표지 없음</div>`;
    return `
        <div class="${className}">
            <img src="${escapeAttr(urls[0])}" alt="" loading="lazy" data-cover-candidates="${escapeAttr(JSON.stringify(urls))}" data-cover-index="0" data-shelf-cover-key="${escapeAttr(book.key)}">
        </div>
    `;
}

function nextCoverCandidate(img) {
    let candidates = [];
    try {
        candidates = JSON.parse(img.getAttribute("data-cover-candidates") || "[]");
    } catch (err) {
        candidates = [];
    }
    const current = Number(img.getAttribute("data-cover-index") || 0);
    const next = candidates[current + 1];
    if (!next) return false;
    img.setAttribute("data-cover-index", String(current + 1));
    img.src = next;
    return true;
}

function coverFallback(img) {
    const parent = img.parentElement;
    if (!parent) return;
    img.remove();
    parent.classList.add("shelf-no-cover");
    parent.textContent = "표지 없음";
}

function persistLoadedCover(img) {
    const index = Number(img.getAttribute("data-cover-index") || 0);
    const key = img.getAttribute("data-shelf-cover-key") || "";
    if (index > 0 && key && shelf && typeof shelf.updateCover === "function") {
        shelf.updateCover(key, img.currentSrc || img.src);
    }
}

function bindCoverUpgrades(scope) {
    const root = scope || document;
    root.querySelectorAll("img[data-cover-candidates]:not([data-cover-bound])").forEach(img => {
        img.setAttribute("data-cover-bound", "1");
        img.addEventListener("error", () => {
            if (!nextCoverCandidate(img)) coverFallback(img);
        });
        img.addEventListener("load", () => {
            if (img.naturalWidth > 0 && img.naturalWidth < MIN_COVER_SOURCE_WIDTH && nextCoverCandidate(img)) return;
            persistLoadedCover(img);
        });
        if (img.complete && img.naturalWidth > 0 && img.naturalWidth < MIN_COVER_SOURCE_WIDTH) {
            nextCoverCandidate(img);
        }
    });
}

function ensureActiveList() {
    const lists = shelf.listAll();
    if (!lists.length) return "";
    if (!activeListId || !lists.some(list => list.id === activeListId)) {
        activeListId = lists[0].id;
        localStorage.setItem(ACTIVE_LIST_KEY, activeListId);
    }
    return activeListId;
}

function setActiveList(listId) {
    activeListId = listId;
    localStorage.setItem(ACTIVE_LIST_KEY, activeListId);
    shelfSharePanel.hidden = true;
    shelfShareUrl.value = "";
    shelfShareStatus.textContent = "";
    setManageOpen(false);
    renderShelf();
}

function setCreateFormOpen(open) {
    shelfCreateForm.hidden = !open;
    shelfCreateToggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) setManageOpen(false);
    if (open) shelfCreateName.focus();
}

function setManageOpen(open) {
    if (!shelfManageActions || !shelfManageToggle) return;
    manageOpen = Boolean(open);
    shelfManageActions.hidden = !open;
    shelfManageToggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) setCreateFormOpen(false);
    updateShelfViewState();
}

function updateShelfViewState() {
    const mode = VIEW_MODES.has(shelfViewMode) ? shelfViewMode : "grid3";
    shelfItems.classList.toggle("is-card", mode !== "list");
    shelfItems.classList.toggle("is-list", mode === "list");
    shelfItems.classList.toggle("is-grid-2", mode === "grid2");
    shelfItems.classList.toggle("is-grid-3", mode === "grid3");
    shelfItems.classList.toggle("is-managing", manageOpen);
    shelfViewButtons.forEach(button => {
        const selected = button.getAttribute("data-shelf-view") === mode;
        button.classList.toggle("is-active", selected);
        button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
}

function setShelfViewMode(mode) {
    if (!VIEW_MODES.has(mode)) return;
    shelfViewMode = mode;
    localStorage.setItem(VIEW_MODE_KEY, shelfViewMode);
    updateShelfViewState();
}

function renderListTabs(lists) {
    shelfListCount.textContent = `${lists.length.toLocaleString()}개`;
    shelfListTabs.innerHTML = lists.map(list => {
        const selected = list.id === activeListId;
        const count = (list.book_keys || []).length;
        return `
            <button class="shelf-list-tab ${selected ? "is-active" : ""}"
                    type="button"
                    role="tab"
                    aria-selected="${selected ? "true" : "false"}"
                    data-shelf-list-id="${escapeAttr(list.id)}">
                <span>${escapeHtml(list.name)}</span>
                <small>${count.toLocaleString()}</small>
            </button>
        `;
    }).join("");
}

function renderShelf() {
    const lists = shelf.listAll();
    ensureActiveList();
    const activeList = shelf.getList(activeListId);
    const books = shelf.booksForList(activeListId);

    renderListTabs(lists);
    shelfListTitle.textContent = "담은 책";
    shelfListDesc.textContent = activeList && activeList.description ? activeList.description : "";
    shelfCount.textContent = `${books.length.toLocaleString()}권`;
    shelfEmpty.hidden = books.length > 0;
    shelfClear.hidden = books.length === 0;
    shelfShare.disabled = books.length === 0;
    shelfDeleteList.disabled = lists.length <= 1;
    shelfDeleteList.hidden = lists.length <= 1;
    updateShelfViewState();
    if (!books.length) {
        shelfSharePanel.hidden = true;
        shelfShareUrl.value = "";
        shelfShareStatus.textContent = "";
    }

    shelfItems.innerHTML = books.map(book => {
        const author = cleanText(book.author);
        const publisher = cleanText(book.publisher);
        const title = cleanText(book.title) || "제목 없음";
        const holding = shelf.countLabel(book);
        return `
            <article class="shelf-item">
                <a class="shelf-item-link" href="${escapeAttr(shelf.detailUrl(book))}" aria-label="${escapeAttr(`${title} 상세로 이동`)}">
                    ${coverHtml(book, "shelf-item-cover")}
                    <div class="shelf-book-main">
                        <h3 title="${escapeAttr(title)}">${escapeHtml(title)}</h3>
                        <div class="shelf-book-meta">
                            ${author ? `<span class="shelf-book-author">${escapeHtml(author)}</span>` : ""}
                            ${publisher ? `<span class="shelf-book-publisher">${escapeHtml(publisher)}</span>` : ""}
                            <span class="shelf-book-holding">${escapeHtml(holding)}</span>
                        </div>
                    </div>
                </a>
                <button class="shelf-remove-button" type="button" data-shelf-remove-key="${escapeAttr(book.key)}" aria-label="${escapeAttr(`${title} 서재에서 빼기`)}">${ICONS.remove}</button>
            </article>
        `;
    }).join("");
    updateShelfViewState();
    bindCoverUpgrades(shelfItems);
}

async function copyShareUrl() {
    const url = shelfShareUrl.value;
    if (!url) return;
    try {
        await navigator.clipboard.writeText(url);
        shelfShareStatus.textContent = "링크를 복사했습니다.";
    } catch (err) {
        shelfShareUrl.focus();
        shelfShareUrl.select();
        shelfShareStatus.textContent = "링크를 선택했습니다.";
    }
}

async function shareActiveList() {
    const activeList = shelf.getList(activeListId);
    const books = shelf.booksForList(activeListId);
    if (!activeList || !books.length) return;
    shelfShare.disabled = true;
    shelfShareStatus.textContent = "공유 링크 생성 중...";
    shelfSharePanel.hidden = false;
    try {
        const response = await fetch("/api/shelves/share", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                list: {
                    id: activeList.id,
                    name: activeList.name,
                    description: activeList.description || "",
                },
                books,
            }),
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "share_failed");
        shelfShareUrl.value = data.url || "";
        shelfShareStatus.textContent = "공유 링크를 만들었습니다.";
        await copyShareUrl();
    } catch (err) {
        console.error(err);
        shelfShareStatus.textContent = err.message || "공유 링크를 만들지 못했습니다.";
    } finally {
        shelfShare.disabled = false;
    }
}

shelfCreateForm.addEventListener("submit", event => {
    event.preventDefault();
    const list = shelf.createList(shelfCreateName.value);
    if (!list) return;
    shelfCreateName.value = "";
    setCreateFormOpen(false);
    setActiveList(list.id);
});

shelfCreateToggle.addEventListener("click", () => {
    setCreateFormOpen(shelfCreateForm.hidden);
});

shelfManageToggle.addEventListener("click", () => {
    setManageOpen(shelfManageActions.hidden);
});

shelfViewButtons.forEach(button => {
    button.addEventListener("click", () => {
        setShelfViewMode(button.getAttribute("data-shelf-view"));
    });
});

shelfCreateName.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    shelfCreateName.value = "";
    setCreateFormOpen(false);
});

shelfListTabs.addEventListener("click", event => {
    const button = event.target.closest("[data-shelf-list-id]");
    if (!button) return;
    setActiveList(button.getAttribute("data-shelf-list-id"));
});

shelfItems.addEventListener("click", event => {
    const button = event.target.closest("[data-shelf-remove-key]");
    if (!button) return;
    shelf.removeFromList(button.getAttribute("data-shelf-remove-key"), activeListId);
    renderShelf();
});

shelfRename.addEventListener("click", () => {
    const activeList = shelf.getList(activeListId);
    if (!activeList) return;
    const nextName = window.prompt("서재 이름", activeList.name);
    if (nextName === null) return;
    const list = shelf.renameList(activeList.id, nextName);
    if (list) {
        setManageOpen(false);
        renderShelf();
    }
});

shelfDeleteList.addEventListener("click", () => {
    const activeList = shelf.getList(activeListId);
    if (!activeList) return;
    if (!window.confirm(`'${activeList.name}' 서재를 삭제할까요? 이 서재에만 담긴 책은 함께 사라집니다.`)) return;
    shelf.deleteList(activeList.id);
    activeListId = "";
    ensureActiveList();
    setManageOpen(false);
    renderShelf();
});

shelfShare.addEventListener("click", () => {
    setManageOpen(false);
    shareActiveList();
});
shelfCopyShare.addEventListener("click", copyShareUrl);

shelfClear.addEventListener("click", () => {
    const activeList = shelf.getList(activeListId);
    const books = shelf.booksForList(activeListId);
    if (!activeList || !books.length) return;
    if (!window.confirm(`'${activeList.name}' 서재에서 모든 책을 뺄까요?`)) return;
    books.forEach(book => shelf.removeFromList(book.key, activeList.id));
    setManageOpen(false);
    renderShelf();
});

window.addEventListener("soulib:shelf-changed", renderShelf);
renderShelf();
