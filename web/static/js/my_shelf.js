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
const shelfRename = document.getElementById("shelf-rename");
const shelfDeleteList = document.getElementById("shelf-delete-list");
const shelf = window.SoulibShelf;
const ACTIVE_LIST_KEY = "soulib.myShelf.activeList";
const ICONS = {
    chevron: '<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"></path></svg>',
    remove: '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"><path d="M6 6l12 12"></path><path d="M18 6 6 18"></path></svg>',
};

let activeListId = localStorage.getItem(ACTIVE_LIST_KEY) || "";

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

function coverHtml(book, className) {
    const imageUrl = cleanText(book.image_url);
    if (!imageUrl) return `<div class="${className} shelf-no-cover">표지 없음</div>`;
    return `
        <div class="${className}">
            <img src="${escapeAttr(imageUrl)}" alt="" loading="lazy" onerror="this.remove(); this.parentElement.classList.add('shelf-no-cover'); this.parentElement.textContent='표지 없음';">
        </div>
    `;
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
    renderShelf();
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
    shelfListTitle.textContent = activeList ? activeList.name : "담은 책";
    shelfListDesc.textContent = activeList && activeList.description ? activeList.description : "";
    shelfCount.textContent = `${books.length.toLocaleString()}권`;
    shelfEmpty.hidden = books.length > 0;
    shelfClear.hidden = books.length === 0;
    shelfDeleteList.disabled = lists.length <= 1;
    shelfDeleteList.hidden = lists.length <= 1;

    shelfItems.innerHTML = books.map(book => {
        const author = cleanText(book.author);
        const publisher = cleanText(book.publisher);
        const title = cleanText(book.title) || "제목 없음";
        return `
            <article class="shelf-item">
                <a class="shelf-item-link" href="${escapeAttr(shelf.detailUrl(book))}" aria-label="${escapeAttr(`${title} 상세로 이동`)}">
                    ${coverHtml(book, "shelf-item-cover")}
                    <div class="shelf-book-main">
                        <h3>${escapeHtml(title)}</h3>
                        <div class="shelf-book-meta">
                            ${author ? `<span class="shelf-book-author">${escapeHtml(author)}</span>` : ""}
                            ${publisher ? `<span class="shelf-book-publisher">${escapeHtml(publisher)}</span>` : ""}
                        </div>
                    </div>
                    <span class="shelf-item-chevron" aria-hidden="true">${ICONS.chevron}</span>
                </a>
                <button class="shelf-remove-button" type="button" data-shelf-remove-key="${escapeAttr(book.key)}" aria-label="${escapeAttr(`${title} 서재에서 빼기`)}">${ICONS.remove}</button>
            </article>
        `;
    }).join("");
}

shelfCreateForm.addEventListener("submit", event => {
    event.preventDefault();
    const list = shelf.createList(shelfCreateName.value);
    if (!list) return;
    shelfCreateName.value = "";
    setActiveList(list.id);
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
    if (list) renderShelf();
});

shelfDeleteList.addEventListener("click", () => {
    const activeList = shelf.getList(activeListId);
    if (!activeList) return;
    if (!window.confirm(`'${activeList.name}' 서재를 삭제할까요? 이 서재에만 담긴 책은 함께 사라집니다.`)) return;
    shelf.deleteList(activeList.id);
    activeListId = "";
    ensureActiveList();
    renderShelf();
});

shelfClear.addEventListener("click", () => {
    const activeList = shelf.getList(activeListId);
    const books = shelf.booksForList(activeListId);
    if (!activeList || !books.length) return;
    if (!window.confirm(`'${activeList.name}' 서재에서 모든 책을 뺄까요?`)) return;
    books.forEach(book => shelf.removeFromList(book.key, activeList.id));
    renderShelf();
});

window.addEventListener("soulib:shelf-changed", renderShelf);
renderShelf();
