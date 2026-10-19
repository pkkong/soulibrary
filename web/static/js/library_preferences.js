(function () {
    const STORAGE_KEY = "soulib.libraryPreferences.v1";
    let registry = [];
    const clean = value => typeof value === "string" ? value.trim().slice(0, 100) : "";

    function configure(values) {
        registry = (Array.isArray(values) ? values : []).filter(value => value && typeof value === "object")
            .map(value => ({code: clean(value.code), name: clean(value.name)}))
            .filter(value => value.code && value.name).slice(0, 100);
    }

    function read() {
        try {
            const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
            if (!value || value.version !== 1 || !Array.isArray(value.libraries) || value.libraries.length > 100) return [];
            return value.libraries.filter(item => item && typeof item === "object")
                .map(item => ({code: clean(item.code), name: clean(item.name)}))
                .filter(item => item.name && (!item.code || /^[a-z0-9_]+$/.test(item.code)));
        } catch (_) { return []; }
    }

    function names() { return [...new Set(read().map(item => item.name))]; }

    function selection(params) {
        if (params.has("libraries")) {
            return [...new Set((params.get("libraries") || "").split(",").map(clean).filter(Boolean)
                .map(value => registry.find(item => item.code === value)?.name || value))];
        }
        return names();
    }

    function save(values, remember) {
        const selected = [...new Set(Array.from(values || []).map(clean).filter(Boolean))];
        try {
            if (!remember || !selected.length) localStorage.removeItem(STORAGE_KEY);
            else {
                const libraries = selected.flatMap(name => {
                    const matching = registry.filter(item => item.name === name || item.code === name);
                    return matching.length ? matching : [{code: "", name}];
                });
                localStorage.setItem(STORAGE_KEY, JSON.stringify({version: 1, libraries}));
            }
            window.dispatchEvent(new CustomEvent("soulib:library-preferences-changed"));
            return true;
        } catch (_) { return false; }
    }

    function options(current, selected) {
        return [...new Set([...registry.map(item => item.name), ...(current || []),
            ...Array.from(selected || []), ...names()].map(clean).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
    }

    function matches(card) {
        const code = clean(card.dataset.libraryCode);
        const name = clean(card.dataset.libraryName) || clean(card.querySelector(".lib-badge-name")?.textContent);
        return read().some(item => (code && item.code === code) || (name && item.name === name));
    }

    function compareCards(a, b) { return Number(matches(b)) - Number(matches(a)); }

    window.addEventListener("storage", event => {
        if (event.key === STORAGE_KEY || event.key === null) {
            window.dispatchEvent(new CustomEvent("soulib:library-preferences-changed"));
        }
    });
    window.SoulibLibraryPreferences = {configure, read, names, selection, save, options, matches, compareCards};
})();
