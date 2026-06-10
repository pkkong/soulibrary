CREATE TABLE IF NOT EXISTS public.shared_shelves (
    id BIGSERIAL PRIMARY KEY,
    slug VARCHAR(40) NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    books JSONB NOT NULL,
    view_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_shared_shelves_slug ON public.shared_shelves(slug);
