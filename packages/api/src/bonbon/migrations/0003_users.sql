-- Users with their display name, so member lists and receipts can show who someone is.
-- Name and e-mail come from the Cognito ID token and are synced on every request
-- (bonbon/auth.py); Cognito stays the source of truth for sign-in.

CREATE TABLE users (
    user_id      text PRIMARY KEY,
    display_name text NOT NULL CHECK (char_length(display_name) >= 1),
    email        text
);

-- Ids that already appear in the data get a placeholder name; the user's next request
-- replaces it with the name from their token.
INSERT INTO users (user_id, display_name)
SELECT user_id, 'Unbekannt' FROM memberships
UNION
SELECT uploaded_by, 'Unbekannt' FROM receipts WHERE uploaded_by IS NOT NULL
UNION
SELECT user_id, 'Unbekannt' FROM join_attempts;

-- Account deletion (feature 05) leaves all households first, so a remaining membership
-- blocks deleting the user. Receipts stay with the household without an uploader.
ALTER TABLE memberships
    ADD FOREIGN KEY (user_id) REFERENCES users;
ALTER TABLE receipts
    ADD FOREIGN KEY (uploaded_by) REFERENCES users ON DELETE SET NULL;
ALTER TABLE join_attempts
    ADD FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE;
-- Without it, deleting a user scans all receipts for the SET NULL.
CREATE INDEX receipts_uploaded_by_idx ON receipts (uploaded_by);
