-- Initial schema, see docs/architecture.md#data-model.
-- Applied by bonbon/handlers/migrate.py in one transaction. Never edit a migration that was
-- applied anywhere; add a new numbered file instead.
--
-- Amounts are integers in Rappen. user_id / created_by / uploaded_by are Cognito user ids
-- ('sub'); there is no users table, so they have no foreign key.

CREATE TABLE households (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    household_id uuid        NOT NULL REFERENCES households ON DELETE CASCADE,
    user_id      text        NOT NULL,
    role         text        NOT NULL CHECK (role IN ('owner', 'member')),
    joined_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (household_id, user_id)
);
-- "Which households is user X in?"
CREATE INDEX memberships_user_id_idx ON memberships (user_id);
-- Exactly one owner per household (at most one here; the app makes sure there is one).
CREATE UNIQUE INDEX memberships_one_owner_idx ON memberships (household_id) WHERE role = 'owner';

CREATE TABLE invite_codes (
    code_hash    text        PRIMARY KEY,
    household_id uuid        NOT NULL REFERENCES households ON DELETE CASCADE,
    created_by   text        NOT NULL,
    expires_at   timestamptz NOT NULL,
    used_at      timestamptz
);
CREATE INDEX invite_codes_household_id_idx ON invite_codes (household_id);

CREATE TABLE categories (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text    NOT NULL UNIQUE
);

CREATE TABLE category_rules (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    keyword     text    NOT NULL UNIQUE,
    category_id integer NOT NULL REFERENCES categories
);

CREATE TABLE receipts (
    -- Created by the API before the upload; it is part of the S3 key.
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id  uuid        NOT NULL REFERENCES households ON DELETE CASCADE,
    -- NULL once the uploader has deleted their account; the receipt stays with the household.
    uploaded_by   text,
    status        text        NOT NULL DEFAULT 'uploaded'
                              CHECK (status IN ('uploaded', 'processing', 'done', 'failed', 'duplicate')),
    s3_key        text        NOT NULL,
    file_hash     text,
    store         text,
    purchase_date date,
    total_rappen  integer,
    raw_textract  jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    processed_at  timestamptz,
    -- The same file uploaded twice to one household is a duplicate.
    UNIQUE (household_id, file_hash)
);
-- Receipt list and monthly reports per household.
CREATE INDEX receipts_household_id_purchase_date_idx ON receipts (household_id, purchase_date);

CREATE TABLE receipt_items (
    receipt_id        uuid           NOT NULL REFERENCES receipts ON DELETE CASCADE,
    position          integer        NOT NULL,
    name              text           NOT NULL,
    -- Weighed goods have fractional quantities (0.452 kg).
    quantity          numeric(10, 3) NOT NULL DEFAULT 1,
    unit_price_rappen integer,
    amount_rappen     integer        NOT NULL,
    category_id       integer        REFERENCES categories,
    PRIMARY KEY (receipt_id, position)
);

-- Rate limit for joining with invite codes.
CREATE TABLE join_attempts (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      text        NOT NULL,
    attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX join_attempts_user_id_attempted_at_idx ON join_attempts (user_id, attempted_at);

-- The API and worker Lambdas connect as bonbon_app: data only (DML), no DDL, no roles.
-- The migration Lambda sets its password and LOGIN from the stack's secret afterwards,
-- so no password is ever stored in this file.
CREATE ROLE bonbon_app NOLOGIN;
GRANT USAGE ON SCHEMA public TO bonbon_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    households, memberships, invite_codes, categories, category_rules,
    receipts, receipt_items, join_attempts
TO bonbon_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO bonbon_app;
-- Tables and sequences created by later migrations get the same rights.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bonbon_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO bonbon_app;
