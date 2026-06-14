import type { BookShelf, SearchBook, ShelfBook } from './types';

const SHELF_KEY = 'soulib.appsInToss.shelf.v1';
const SHELVES_KEY = 'soulib.appsInToss.shelves.v1';
const DEFAULT_SHELF_ID = 'default';
const DEFAULT_SHELF_NAME = '기본 서재';

export function bookKey(book: SearchBook) {
  const stable = [book.title, book.author || '', book.publisher || '']
    .map((value) => value.trim().toLowerCase())
    .join('|');
  return book.live_detail_key || stable;
}

function nowIso() {
  return new Date().toISOString();
}

function makeShelfId() {
  return `shelf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeBook(item: Partial<ShelfBook> | null | undefined): ShelfBook | null {
  if (!item?.title) return null;
  const key = typeof item.key === 'string' && item.key.trim() ? item.key : bookKey(item as SearchBook);
  if (!key) return null;
  return {
    ...(item as SearchBook),
    title: item.title,
    key,
    savedAt: item.savedAt || nowIso(),
  };
}

function normalizeBooks(value: unknown): ShelfBook[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value.reduce<ShelfBook[]>((books, item) => {
    const book = normalizeBook(item as Partial<ShelfBook>);
    if (!book || seen.has(book.key)) return books;
    seen.add(book.key);
    books.push(book);
    return books;
  }, []);
}

function makeDefaultShelf(books: ShelfBook[] = []): BookShelf {
  const timestamp = nowIso();
  return {
    id: DEFAULT_SHELF_ID,
    name: DEFAULT_SHELF_NAME,
    books,
    createdAt: timestamp,
    updatedAt: timestamp,
    isDefault: true,
  };
}

function normalizeShelf(item: Partial<BookShelf> | null | undefined, index: number): BookShelf | null {
  const books = normalizeBooks(item?.books);
  const id = String(item?.id || '').trim() || (index === 0 ? DEFAULT_SHELF_ID : makeShelfId());
  const name = String(item?.name || '').trim() || (index === 0 ? DEFAULT_SHELF_NAME : `서재 ${index + 1}`);
  const timestamp = nowIso();
  return {
    id,
    name,
    books,
    createdAt: item?.createdAt || timestamp,
    updatedAt: item?.updatedAt || timestamp,
    isDefault: item?.isDefault || id === DEFAULT_SHELF_ID,
  };
}

function ensureShelves(value: unknown): BookShelf[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const shelves = value.reduce<BookShelf[]>((items, raw, index) => {
    const shelf = normalizeShelf(raw as Partial<BookShelf>, index);
    if (!shelf) return items;
    let id = shelf.id;
    while (seen.has(id)) {
      id = makeShelfId();
    }
    seen.add(id);
    items.push({ ...shelf, id, isDefault: shelf.isDefault || id === DEFAULT_SHELF_ID });
    return items;
  }, []);

  if (!shelves.length) return [makeDefaultShelf()];
  if (!shelves.some((shelf) => shelf.isDefault)) {
    return shelves.map((shelf, index) => (index === 0 ? { ...shelf, isDefault: true } : shelf));
  }
  return shelves;
}

export function getShelf(): ShelfBook[] {
  try {
    const raw = window.localStorage.getItem(SHELF_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return normalizeBooks(parsed);
  } catch {
    return [];
  }
}

export function saveShelf(books: ShelfBook[]) {
  window.localStorage.setItem(SHELF_KEY, JSON.stringify(books));
}

export function getShelves(): BookShelf[] {
  try {
    const raw = window.localStorage.getItem(SHELVES_KEY);
    if (raw) {
      const shelves = ensureShelves(JSON.parse(raw));
      if (shelves.length) return shelves;
    }
  } catch {
    // Fall back to the legacy single shelf below.
  }
  return [makeDefaultShelf(getShelf())];
}

export function saveShelves(shelves: BookShelf[]) {
  window.localStorage.setItem(SHELVES_KEY, JSON.stringify(ensureShelves(shelves)));
}

export function createShelf(name: string, shelves: BookShelf[]) {
  const cleanName = name.trim() || `서재 ${shelves.length + 1}`;
  const timestamp = nowIso();
  return {
    id: makeShelfId(),
    name: cleanName,
    books: [],
    createdAt: timestamp,
    updatedAt: timestamp,
  } satisfies BookShelf;
}

export function isBookSaved(book: SearchBook, shelves: BookShelf[]) {
  const key = bookKey(book);
  return shelves.some((shelf) => shelf.books.some((item) => item.key === key));
}

export function isBookInShelf(book: SearchBook, shelf: BookShelf) {
  const key = bookKey(book);
  return shelf.books.some((item) => item.key === key);
}

export function addBook(book: SearchBook, books: ShelfBook[]) {
  const key = bookKey(book);
  if (!book.title || books.some((item) => item.key === key)) {
    return books;
  }
  return [
    {
      ...book,
      key,
      savedAt: new Date().toISOString(),
    },
    ...books,
  ];
}

export function removeBook(bookOrKey: SearchBook | string, books: ShelfBook[]) {
  const key = typeof bookOrKey === 'string' ? bookOrKey : bookKey(bookOrKey);
  return books.filter((item) => item.key !== key);
}

export function setBookInShelf(book: SearchBook, shelf: BookShelf, selected: boolean): BookShelf {
  const books = selected ? addBook(book, shelf.books) : removeBook(book, shelf.books);
  return {
    ...shelf,
    books,
    updatedAt: nowIso(),
  };
}
