import type {
  LibraryItem,
  BookDetailResponse,
  LiveSearchResponse,
  SearchBook,
  SearchField,
  SearchFilters,
} from './types';

const DEFAULT_API_BASE = 'https://www.soulib.kr';

export const API_BASE =
  (import.meta.env.VITE_SOULIB_API_BASE || DEFAULT_API_BASE).replace(/\/+$/, '') || DEFAULT_API_BASE;

export type LibraryStatus = {
  loaned?: number;
  total?: number;
  owned?: number;
  reserved?: number;
};

type LibraryStatusResponse = {
  status?: LibraryStatus | null;
};

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

function inferStatusKind(library: LibraryItem) {
  const kind = library.status_kind || '';
  if (kind) return kind;
  const platform = library.platform_code || '';
  const code = library.code || '';
  if (platform === 'Kyobo_New') return 'kyobo';
  if (platform === 'Kyobo' || code === 'dobong') return 'dobong';
  if (platform === 'YES24') return 'yes24';
  if (platform === 'Bookcube') return 'bookcube';
  if (code === 'gangnam' || platform === 'Gangnam') return 'gangnam';
  if (code === 'eunpyeong' || platform === 'Eunpyeong') return 'eunpyeong';
  if (code === 'seoul' || platform === 'SeoulLibrary') return 'seoul';
  if (code === 'sen_owned' || code === 'sen_subs' || platform === 'SeoulEducation') return 'sen';
  return '';
}

async function readJson<T extends { error?: string; message?: string }>(response: Response): Promise<T> {
  const data = (await response.json()) as T;
  if (!response.ok || data.error) {
    throw new ApiError(data.error || data.message || '요청을 처리하지 못했습니다.', response.status);
  }
  return data;
}

export async function searchBooks(
  query: string,
  field: SearchField,
  filters: SearchFilters = {},
  page: { limit?: number; offset?: number } = {},
): Promise<LiveSearchResponse> {
  const response = await fetch(
    buildUrl('/api/live_search', {
      query,
      field,
      providers: filters.providers?.join(','),
      libraries: filters.libraries?.join(','),
      limit: page.limit || 20,
      offset: page.offset || 0,
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

function statusEndpoint(library: LibraryItem) {
  if (library.service_type === 'Subscription') {
    return null;
  }
  const kind = inferStatusKind(library);
  if (kind === 'kyobo') {
    return buildUrl('/api/kyobo_status', {
      library_code: library.code || '',
      brcd: library.brcd || '',
      ctts_dvsn_code: library.ctts_dvsn_code || '',
      ctgr_id: library.ctgr_id || '',
      sntn_auth_code: library.sntn_auth_code || '',
    });
  }
  if (kind === 'dobong') {
    return buildUrl('/api/dobong_status', {
      brcd: library.brcd || '',
      product_cd: library.product_cd || '',
      category_id: library.category_id || '',
    });
  }
  if (kind === 'yes24') {
    return buildUrl('/api/yes24_status', {
      library_code: library.code || '',
      goods_id: library.goods_id || '',
    });
  }
  if (kind === 'bookcube') {
    return buildUrl('/api/bookcube_status', {
      library_code: library.code || '',
      content_id: library.content_id || '',
    });
  }
  if (kind === 'gangnam') {
    return buildUrl('/api/gangnam_status', {
      library_code: library.code || '',
      content_id: library.content_id || '',
    });
  }
  if (kind === 'eunpyeong') {
    return buildUrl('/api/eunpyeong_status', {
      content_id: library.content_id || '',
    });
  }
  if (kind === 'seoul') {
    return buildUrl('/api/seoul_status', {
      content_id: library.content_id || '',
    });
  }
  if (kind === 'sen') {
    return buildUrl('/api/sen_status', {
      library_code: library.code || '',
      content_id: library.content_id || '',
    });
  }
  return null;
}

export async function getLibraryStatus(library: LibraryItem): Promise<LibraryStatus> {
  const endpoint = statusEndpoint(library);
  if (!endpoint) {
    throw new Error('unsupported_status_source');
  }
  const response = await fetch(endpoint, {
    headers: { Accept: 'application/json' },
  });
  const data = (await response.json()) as LibraryStatusResponse;
  const status = (data && data.status) || null;
  if (!response.ok || !status) {
    throw new Error('status_fetch_failed');
  }
  return status;
}

export function apiErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}
