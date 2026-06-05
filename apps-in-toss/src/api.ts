import type {
  BookDetailResponse,
  CreateReportResponse,
  LiveSearchResponse,
  RecentReportsResponse,
  ReportPayload,
  SearchBook,
  SearchField,
} from './types';

const DEFAULT_API_BASE = 'https://www.soulib.kr';

export const API_BASE =
  (import.meta.env.VITE_SOULIB_API_BASE || DEFAULT_API_BASE).replace(/\/+$/, '') || DEFAULT_API_BASE;

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function buildUrl(path: string, params?: Record<string, string | number | undefined>) {
  const url = new URL(path, `${API_BASE}/`);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && String(value).trim()) {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

async function readJson<T extends { error?: string; message?: string }>(response: Response): Promise<T> {
  const data = (await response.json()) as T;
  if (!response.ok || data.error) {
    throw new ApiError(data.error || data.message || '요청을 처리하지 못했습니다.', response.status);
  }
  return data;
}

export async function searchBooks(query: string, field: SearchField): Promise<LiveSearchResponse> {
  const response = await fetch(
    buildUrl('/api/live_search', {
      query,
      field,
      limit: 20,
      offset: 0,
    }),
    {
      headers: { Accept: 'application/json' },
    },
  );
  return readJson<LiveSearchResponse>(response);
}

export async function getBookDetail(book: SearchBook): Promise<BookDetailResponse> {
  const response = await fetch(
    buildUrl('/api/live_book_detail', {
      key: book.live_detail_key,
      title: book.title,
      author: book.author,
      publisher: book.publisher,
    }),
    {
      headers: { Accept: 'application/json' },
    },
  );
  return readJson<BookDetailResponse>(response);
}

export async function getRecentReports(): Promise<RecentReportsResponse> {
  const response = await fetch(buildUrl('/api/reports/recent'), {
    headers: { Accept: 'application/json' },
  });
  const data = (await response.json()) as RecentReportsResponse;
  if (!response.ok && !data.unavailable) {
    throw new ApiError('최근 접수 상태를 불러오지 못했습니다.', response.status);
  }
  return data;
}

export async function submitReport(payload: ReportPayload): Promise<CreateReportResponse> {
  const response = await fetch(buildUrl('/api/reports'), {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      category: payload.category || '오류',
      message: payload.message,
      page_url: payload.page_url || '',
    }),
  });
  return readJson<CreateReportResponse>(response);
}

export function apiErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}
