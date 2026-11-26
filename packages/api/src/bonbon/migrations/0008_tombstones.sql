-- Tombstones for account deletion (feature 05). When a user deletes their account, the worker
-- records their Cognito id here before removing their data. auth.current_user_id() rejects any
-- request from a tombstoned id with 401, so an ID token issued before the deletion (valid until
-- it expires, up to ~60 min) can't recreate the users row or join a household mid-deletion.
--
-- Only the Cognito sub, no personal data: the point is to forget the person, not to keep a
-- record of them. The row outlives the users row (which the worker deletes) and stays, so a
-- deleted account can never be silently resurrected.

CREATE TABLE tombstones (
    user_id    text        PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);
