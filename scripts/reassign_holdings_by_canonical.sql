WITH canon AS (
  SELECT canonical_id, MIN(book_id) AS rep_book_id
  FROM holdings
  WHERE canonical_id IS NOT NULL AND canonical_id <> ''
  GROUP BY canonical_id
),
moves AS (
  SELECT h.id, c.rep_book_id
  FROM holdings h
  JOIN canon c ON c.canonical_id = h.canonical_id
  WHERE h.book_id <> c.rep_book_id
)
UPDATE holdings h
SET book_id = m.rep_book_id
FROM moves m
WHERE h.id = m.id;

WITH book_canon AS (
  SELECT book_id, MIN(canonical_id) AS canonical_id
  FROM holdings
  WHERE canonical_id IS NOT NULL AND canonical_id <> ''
  GROUP BY book_id
  HAVING COUNT(DISTINCT canonical_id) = 1
)
UPDATE books b
SET canonical_id = bc.canonical_id
FROM book_canon bc
WHERE b.id = bc.book_id;

WITH dup AS (
  SELECT canonical_id, MIN(id) AS keep_id, array_agg(id) AS ids
  FROM books
  WHERE canonical_id IS NOT NULL AND canonical_id <> ''
  GROUP BY canonical_id
  HAVING COUNT(*) > 1
),
update_holdings AS (
  UPDATE holdings h
  SET book_id = d.keep_id
  FROM dup d
  WHERE h.book_id = ANY(d.ids)
    AND h.book_id <> d.keep_id
  RETURNING h.id
)
DELETE FROM books b
USING dup d
WHERE b.id = ANY(d.ids)
  AND b.id <> d.keep_id;
