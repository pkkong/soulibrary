(function () {
    let active = null;
    const selector = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    function controls(dialog) {
        return Array.from(dialog.querySelectorAll(selector)).filter(element =>
            !element.hidden && !element.closest('[hidden], [inert]') && element.getClientRects().length &&
            getComputedStyle(element).visibility !== 'hidden'
        );
    }

    function close(dialog) {
        if (!active || (dialog && active.dialog !== dialog)) return;
        const previous = active;
        active = null;
        previous.background.forEach(([element, inert]) => { element.inert = inert; });
        if (previous.trigger && previous.trigger.isConnected) previous.trigger.focus({preventScroll: true});
    }

    function open(dialog, options = {}) {
        if (!dialog || (active && active.dialog === dialog)) return;
        const trigger = options.trigger || document.activeElement;
        close();
        const background = [];
        // A dialog may live inside main. Isolate siblings at every ancestor,
        // including the page content next to that dialog, rather than only body.
        let branch = dialog;
        while (branch.parentElement) {
            const parent = branch.parentElement;
            Array.from(parent.children).forEach(element => {
                if (element === branch || element === options.backdrop ||
                    (options.backdrop && element.contains(options.backdrop)) ||
                    /^(SCRIPT|STYLE|LINK)$/.test(element.tagName)) return;
                background.push([element, element.inert]);
                element.inert = true;
            });
            if (parent === document.body) break;
            branch = parent;
        }
        active = {dialog, background, trigger, onClose: options.onClose};
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        if (!dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1');
        function focusWhenVisible(attempt = 0) {
            if (!active || active.dialog !== dialog || dialog.contains(document.activeElement)) return;
            const target = options.initialFocus || controls(dialog)[0] || dialog;
            target.focus({preventScroll: true});
            // CSS visibility transitions can reject focus in the opening frame.
            if (!dialog.contains(document.activeElement) && attempt < 12) {
                requestAnimationFrame(() => focusWhenVisible(attempt + 1));
            }
        }
        focusWhenVisible();
    }

    document.addEventListener('keydown', event => {
        if (!active) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopImmediatePropagation();
            const current = active;
            if (current.onClose) current.onClose();
            close(current.dialog);
        } else if (event.key === 'Tab') {
            const items = controls(active.dialog);
            const first = items[0] || active.dialog;
            const last = items[items.length - 1] || active.dialog;
            if (!items.length || !active.dialog.contains(document.activeElement) ||
                (event.shiftKey && document.activeElement === first) ||
                (!event.shiftKey && document.activeElement === last)) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            }
        }
    }, true);
    document.addEventListener('focusin', event => {
        if (active && !active.dialog.contains(event.target)) (controls(active.dialog)[0] || active.dialog).focus();
    });
    window.SoulibDialog = {open, close};
})();
