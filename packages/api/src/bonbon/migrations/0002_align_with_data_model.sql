-- Aligns the schema with the data model in the report (chapter 4.3).

-- A second upload of the same file is kept with status 'duplicate', so a file hash must be
-- unique per household only among the other receipts. The full UNIQUE constraint from 0001
-- would reject the duplicate row instead.
ALTER TABLE receipts DROP CONSTRAINT receipts_household_id_file_hash_key;
CREATE UNIQUE INDEX receipts_household_id_file_hash_idx
    ON receipts (household_id, file_hash)
    WHERE status <> 'duplicate';

-- Every receipt item has exactly one category. Items that match no keyword rule get
-- 'Sonstiges'; the other categories come with the categorization feature.
INSERT INTO categories (name) VALUES ('Sonstiges');
ALTER TABLE receipt_items ALTER COLUMN category_id SET NOT NULL;

-- Not part of the data model:
-- s3_key is derived from household and receipt id (bonbon/receipts/storage.py),
-- the raw Textract result is kept in S3 (docs/decisions/0007),
-- and no feature needs to know who created an invite code.
ALTER TABLE receipts DROP COLUMN s3_key, DROP COLUMN raw_textract;
ALTER TABLE invite_codes DROP COLUMN created_by;
