import type { SearchBook, ShelfBook } from './types';

const SHELF_KEY = 'soulib.appsInToss.shelf.v1';

function bookKey(book: SearchBook) {
  const stable = [book.title, book.author || '', book.publisher || '']
    .map((value) => value.trim().toLowerCase())
    .join('|');
  return book.live_detail_key || stable;
}

export function getShelf(): ShelfBook[] {
  try {
    const raw = window.localStorage.getItem(SHELF_KEY);
    const parsed = raw ? (JSON.parse(raw) as ShelfBook[]) : [];
    return Array.isArray(parsed) ? parsed.filter((item) => item.title && item.key) : [];
  } catch {
    return [];
  }
}

export function saveShelf(books: ShelfBook[]) {
  window.localStorage.setItem(SHELF_KEY, JSON.stringify(books));
}

export function isBookSaved(book: SearchBook, books: ShelfBook[]) {
  const key = bookKey(book);
  return books.some((item) => item.key === key);
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
