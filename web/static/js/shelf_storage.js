(function () {
    const STORAGE_KEY = "soulib.myShelf.v1";
    const DEFAULT_LIST_ID = "default";
    const DEFAULT_LIST_NAME = "기본 서재";

    function cleanText(value) {
        return String(value || "").trim();
    }

    function normalizeKeyPart(value) {
        return cleanText(value).toLowerCase().replace(/[\s\[\]\(\){}<>.,/|\\\-_:;"'`~!?]/g, "");
    }

    function nowIso() {
        return new Date().toISOString();
    }

    function uid() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID().slice(0, 13);
        }
        return `shelf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    }

    function emptyState() {
        const now = nowIso();
        return {
            version: 2,
            lists: [
                {
                    id: DEFAULT_LIST_ID,
                    name: DEFAULT_LIST_NAME,
                    description: "",
                    created_at: now,
                    updated_at: now,
                    book_keys: [],
                },
            ],
            books: {},
        };
    }

    function normalizeList(list) {
        const id = cleanText(list && list.id) || uid();
        const now = nowIso();
        const keys = Array.isArray(list && list.book_keys) ? list.book_keys : [];
        return {
            id,
            name: cleanText(list && list.name) || DEFAULT_LIST_NAME,
            description: cleanText(list && list.description),
            created_at: cleanText(list && list.created_at) || now,
            updated_at: cleanText(list && list.updated_at) || now,
            book_keys: [...new Set(keys.map(cleanText).filter(Boolean))],
        };
    }

    function migrateLegacyArray(raw) {
        const state = emptyState();
        const books = {};
        const keys = [];
        raw.forEach(book => {
            if (!book || !book.title) return;
            const item = toShelfBook(book);
            books[item.key] = item;
            keys.push(item.key);
        });
        state.books = books;
        state.lists[0].book_keys = [...new Set(keys)];
        return state;
    }

    function normalizeState(raw) {
        if (Array.isArray(raw)) return migrateLegacyArray(raw);
        if (!raw || typeof raw !== "object") return emptyState();
        if (raw.version !== 2 || !Array.isArray(raw.lists) || !raw.books || typeof raw.books !== "object") {
            return emptyState();
        }

        const state = {
            version: 2,
            lists: raw.lists.map(normalizeList),
            books: {},
        };
        Object.entries(raw.books).forEach(([key, book]) => {
            const item = toShelfBook({ ...book, key });
            if (item.title) state.books[item.key] = item;
        });
        if (!state.lists.length) state.lists = emptyState().lists;
        const knownKeys = new Set(Object.keys(state.books));
        state.lists.forEach(list => {
            list.book_keys = list.book_keys.filter(key => knownKeys.has(key));
        });
        pruneUnlistedBooks(state);
        return state;
    }

    function loadState() {
        try {
            return normalizeState(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"));
        } catch (err) {
            console.error(err);
            return emptyState();
        }
    }

    function saveState(state) {
        const normalized = normalizeState(state);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
        return normalized;
    }

    function pruneUnlistedBooks(state) {
        const referenced = new Set();
        state.lists.forEach(list => {
            list.book_keys.forEach(key => referenced.add(key));
        });
        Object.keys(state.books).forEach(key => {
            if (!referenced.has(key)) delete state.books[key];
        });
    }

    function keyFor(book) {
        const directKey = cleanText(book && book.key);
        if (directKey) return directKey;
        const liveKey = cleanText(book && book.live_detail_key);
        if (liveKey) return `live:${liveKey}`;
        const title = normalizeKeyPart(book && book.title);
        const author = normalizeKeyPart(book && book.author);
        const publisher = normalizeKeyPart(book && book.publisher);
        return `meta:${title}|${author}|${publisher}`;
    }

    function detailUrl(book) {
        if (book && book.live_detail_url) return book.live_detail_url;
        if (book && book.book_id) return `/book/${encodeURIComponent(book.book_id)}`;
        const title = cleanText(book && book.title);
        if (!title) return "/search";
        const params = new URLSearchParams();
        params.set("title", title);
        const author = cleanText(book && book.author);
        const publisher = cleanText(book && book.publisher);
        const liveKey = cleanText(book && book.live_detail_key);
        if (author) params.set("author", author);
        if (publisher) params.set("publisher", publisher);
        if (liveKey) params.set("key", liveKey);
        return `/live_book?${params.toString()}`;
    }

    function countLabel(book) {
        const counts = (book && book.counts) || {};
        const total = Number(counts.total || 0);
        if (!Number.isFinite(total) || total <= 0) return "소장 정보 확인 필요";
        const parts = [];
        const kyobo = Number(counts.kyobo || 0);
        const yes24 = Number(counts.yes24 || 0);
        const other = Number(counts.other || 0);
        if (kyobo > 0) parts.push(`교보 ${kyobo}`);
        if (yes24 > 0) parts.push(`YES24 ${yes24}`);
        if (other > 0) parts.push(`기타 ${other}`);
        return `도서관 ${total}곳${parts.length ? ` · ${parts.join(" · ")}` : ""}`;
    }

    function toShelfBook(book) {
        const key = keyFor(book || {});
        return {
            key,
            title: cleanText(book && book.title),
            author: cleanText(book && book.author),
            publisher: cleanText(book && book.publisher),
            image_url: cleanText(book && book.image_url),
            live_detail_key: cleanText(book && book.live_detail_key),
            live_detail_url: detailUrl(book || {}),
            book_id: (book && book.book_id) || null,
            counts: (book && book.counts) || {},
            added_at: cleanText(book && book.added_at) || nowIso(),
            updated_at: nowIso(),
        };
    }

    function listAll() {
        return loadState().lists;
    }

    function getList(listId) {
        const state = loadState();
        return state.lists.find(list => list.id === listId) || state.lists[0];
    }

    function createList(name, description) {
        const state = loadState();
        const cleanName = cleanText(name);
        if (!cleanName) return null;
        const now = nowIso();
        const list = {
            id: uid(),
            name: cleanName.slice(0, 80),
            description: cleanText(description).slice(0, 200),
            created_at: now,
            updated_at: now,
            book_keys: [],
        };
        state.lists.push(list);
        saveState(state);
        emitChanged("create-list", { list });
        return list;
    }

    function renameList(listId, name) {
        const state = loadState();
        const list = state.lists.find(item => item.id === listId);
        const cleanName = cleanText(name);
        if (!list || !cleanName) return null;
        list.name = cleanName.slice(0, 80);
        list.updated_at = nowIso();
        saveState(state);
        emitChanged("rename-list", { list });
        return list;
    }

    function deleteList(listId) {
        const state = loadState();
        if (state.lists.length <= 1) return false;
        const idx = state.lists.findIndex(item => item.id === listId);
        if (idx < 0) return false;
        const [list] = state.lists.splice(idx, 1);
        pruneUnlistedBooks(state);
        saveState(state);
        emitChanged("delete-list", { list });
        return true;
    }

    function listsForBook(key) {
        const state = loadState();
        return state.lists.filter(list => list.book_keys.includes(key));
    }

    function has(key, listId) {
        const state = loadState();
        if (listId) {
            const list = state.lists.find(item => item.id === listId);
            return !!(list && list.book_keys.includes(key));
        }
        return state.lists.some(list => list.book_keys.includes(key));
    }

    function add(book, listId) {
        const state = loadState();
        const item = toShelfBook(book || {});
        if (!item.title) return null;
        const existing = state.books[item.key];
        if (existing && existing.added_at) item.added_at = existing.added_at;
        const targetId = listId || state.lists[0].id;
        let list = state.lists.find(entry => entry.id === targetId);
        if (!list) list = state.lists[0];
        state.books[item.key] = item;
        list.book_keys = [item.key, ...list.book_keys.filter(key => key !== item.key)];
        list.updated_at = nowIso();
        saveState(state);
        emitChanged("add", { item, list });
        return item;
    }

    function removeFromList(key, listId) {
        const state = loadState();
        const list = state.lists.find(item => item.id === listId);
        if (!list) return;
        list.book_keys = list.book_keys.filter(itemKey => itemKey !== key);
        list.updated_at = nowIso();
        pruneUnlistedBooks(state);
        saveState(state);
        emitChanged("remove", { key, list });
    }

    function removeFromAll(key) {
        const state = loadState();
        state.lists.forEach(list => {
            list.book_keys = list.book_keys.filter(itemKey => itemKey !== key);
        });
        delete state.books[key];
        saveState(state);
        emitChanged("remove-all", { key });
    }

    function booksForList(listId) {
        const state = loadState();
        const list = state.lists.find(item => item.id === listId) || state.lists[0];
        return list.book_keys.map(key => state.books[key]).filter(Boolean);
    }

    function emitChanged(action, detail) {
        window.dispatchEvent(new CustomEvent("soulib:shelf-changed", { detail: { action, ...(detail || {}) } }));
    }

    window.SoulibShelf = {
        add,
        booksForList,
        countLabel,
        createList,
        deleteList,
        detailUrl,
        getList,
        has,
        keyFor,
        listAll,
        listsForBook,
        loadState,
        removeFromAll,
        removeFromList,
        renameList,
        saveState,
        toShelfBook,
    };
})();
