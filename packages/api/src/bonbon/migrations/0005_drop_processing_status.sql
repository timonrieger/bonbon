-- The database worker takes a receipt from 'uploaded' straight to 'done', 'failed' or
-- 'duplicate' in one transaction (docs/decisions/0007). A crash rolls everything back and the
-- retry starts clean, so no receipt gets stuck half-processed. 'processing' was never written;
-- the app shows 'uploaded' as "in Bearbeitung".
ALTER TABLE receipts DROP CONSTRAINT receipts_status_check;
ALTER TABLE receipts ADD CONSTRAINT receipts_status_check
    CHECK (status IN ('uploaded', 'done', 'failed', 'duplicate'));
