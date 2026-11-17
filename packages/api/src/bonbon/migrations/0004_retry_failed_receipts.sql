-- A failed receipt may be uploaded again: the new upload is processed instead of being marked
-- as a duplicate of the failed one. So a file hash is unique per household only among the
-- receipts that are neither duplicates nor failed (replaces the index from 0002).
DROP INDEX receipts_household_id_file_hash_idx;
CREATE UNIQUE INDEX receipts_household_id_file_hash_idx
    ON receipts (household_id, file_hash)
    WHERE status NOT IN ('duplicate', 'failed');
