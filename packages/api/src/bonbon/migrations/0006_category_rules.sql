-- Seeds the fixed category list and the keyword rules the database worker uses to categorize
-- items (docs/features/02-extraction-categorization.md, proposal chapter 2 "Kategorisierung").
-- The categories and category_rules tables already exist (0001); 'Sonstiges' already exists
-- (0002). An item that matches no keyword stays 'Sonstiges'.
--
-- Categories are the German UI names (the API returns categories.name straight to the
-- frontend, like 'Sonstiges'). Keywords are lowercase; the worker lowercases the item name
-- before matching, so the comparison is case-insensitive. keyword is UNIQUE, so every keyword
-- maps to exactly one category and the seed stays idempotent on its own (one INSERT per file).

INSERT INTO categories (name) VALUES
    ('Früchte & Gemüse'),
    ('Milchprodukte & Eier'),
    ('Brot & Backwaren'),
    ('Fleisch & Fisch'),
    ('Getränke'),
    ('Süsswaren & Snacks'),
    ('Tiefkühl & Konserven'),
    ('Grundnahrungsmittel'),
    ('Haushalt & Reinigung'),
    ('Körperpflege & Gesundheit')
ON CONFLICT (name) DO NOTHING;

-- keyword -> category. Lowercase, matched as a substring of the lowercased item name, so
-- 'bio apfel' matches the keyword 'apfel'. Swiss product wording (Migros, Coop, Aldi, Lidl).
INSERT INTO category_rules (keyword, category_id)
SELECT keyword, categories.id
FROM (VALUES
    -- Früchte & Gemüse
    ('apfel',        'Früchte & Gemüse'),
    ('banane',       'Früchte & Gemüse'),
    ('tomate',       'Früchte & Gemüse'),
    ('gurke',        'Früchte & Gemüse'),
    ('salat',        'Früchte & Gemüse'),
    ('karotte',      'Früchte & Gemüse'),
    ('rüebli',       'Früchte & Gemüse'),
    ('zwiebel',      'Früchte & Gemüse'),
    ('kartoffel',    'Früchte & Gemüse'),
    ('zitrone',      'Früchte & Gemüse'),
    ('orange',       'Früchte & Gemüse'),
    ('beeren',       'Früchte & Gemüse'),
    ('erdbeer',      'Früchte & Gemüse'),
    ('paprika',      'Früchte & Gemüse'),
    -- Milchprodukte & Eier
    ('milch',        'Milchprodukte & Eier'),
    ('vollmilch',    'Milchprodukte & Eier'),
    ('rahm',         'Milchprodukte & Eier'),
    ('joghurt',      'Milchprodukte & Eier'),
    ('jogurt',       'Milchprodukte & Eier'),
    ('käse',         'Milchprodukte & Eier'),
    ('butter',       'Milchprodukte & Eier'),
    ('quark',        'Milchprodukte & Eier'),
    ('gruyère',      'Milchprodukte & Eier'),
    ('crème',        'Milchprodukte & Eier'),
    ('eier',         'Milchprodukte & Eier'),
    ('freiland ei',  'Milchprodukte & Eier'),
    -- Brot & Backwaren
    ('brot',         'Brot & Backwaren'),
    ('brötchen',     'Brot & Backwaren'),
    ('gipfel',       'Brot & Backwaren'),
    ('croissant',    'Brot & Backwaren'),
    ('zopf',         'Brot & Backwaren'),
    ('toast',        'Brot & Backwaren'),
    ('weggli',       'Brot & Backwaren'),
    -- Fleisch & Fisch
    ('poulet',       'Fleisch & Fisch'),
    ('hähnchen',     'Fleisch & Fisch'),
    ('rind',         'Fleisch & Fisch'),
    ('schwein',      'Fleisch & Fisch'),
    ('hack',         'Fleisch & Fisch'),
    ('wurst',        'Fleisch & Fisch'),
    ('schinken',     'Fleisch & Fisch'),
    ('speck',        'Fleisch & Fisch'),
    ('lachs',        'Fleisch & Fisch'),
    ('fisch',        'Fleisch & Fisch'),
    ('thon',         'Fleisch & Fisch'),
    ('salami',       'Fleisch & Fisch'),
    ('salametti',    'Fleisch & Fisch'),
    -- Getränke
    ('wasser',       'Getränke'),
    ('mineral',      'Getränke'),
    ('cola',         'Getränke'),
    ('rivella',      'Getränke'),
    ('saft',         'Getränke'),
    ('bier',         'Getränke'),
    ('wein',         'Getränke'),
    ('kaffee',       'Getränke'),
    ('tee',          'Getränke'),
    ('ice tea',      'Getränke'),
    -- Süsswaren & Snacks
    ('schokolade',   'Süsswaren & Snacks'),
    ('schoggi',      'Süsswaren & Snacks'),
    ('schoko',       'Süsswaren & Snacks'),
    ('chocolat',     'Süsswaren & Snacks'),
    ('guetzli',      'Süsswaren & Snacks'),
    ('keks',         'Süsswaren & Snacks'),
    ('chips',        'Süsswaren & Snacks'),
    ('bonbon',       'Süsswaren & Snacks'),
    ('biscuit',      'Süsswaren & Snacks'),
    ('lebkuchen',    'Süsswaren & Snacks'),
    ('glace',        'Süsswaren & Snacks'),
    -- Tiefkühl & Konserven
    ('pizza',        'Tiefkühl & Konserven'),
    ('tiefkühl',     'Tiefkühl & Konserven'),
    ('pommes',       'Tiefkühl & Konserven'),
    ('konserve',     'Tiefkühl & Konserven'),
    ('dose',         'Tiefkühl & Konserven'),
    -- Grundnahrungsmittel
    ('mehl',         'Grundnahrungsmittel'),
    ('zucker',       'Grundnahrungsmittel'),
    ('salz',         'Grundnahrungsmittel'),
    ('reis',         'Grundnahrungsmittel'),
    ('teigwaren',    'Grundnahrungsmittel'),
    ('pasta',        'Grundnahrungsmittel'),
    ('spaghetti',    'Grundnahrungsmittel'),
    ('hörnli',       'Grundnahrungsmittel'),
    ('öl',           'Grundnahrungsmittel'),
    ('essig',        'Grundnahrungsmittel'),
    ('müesli',       'Grundnahrungsmittel'),
    -- Haushalt & Reinigung
    ('waschmittel',  'Haushalt & Reinigung'),
    ('abwasch',      'Haushalt & Reinigung'),
    ('wc-papier',    'Haushalt & Reinigung'),
    ('haushaltpapier', 'Haushalt & Reinigung'),
    ('müllsack',     'Haushalt & Reinigung'),
    ('reiniger',     'Haushalt & Reinigung'),
    ('teelicht',     'Haushalt & Reinigung'),
    -- Körperpflege & Gesundheit
    ('shampoo',      'Körperpflege & Gesundheit'),
    ('seife',        'Körperpflege & Gesundheit'),
    ('zahnpasta',    'Körperpflege & Gesundheit'),
    ('duschgel',     'Körperpflege & Gesundheit'),
    ('deo',          'Körperpflege & Gesundheit'),
    ('windel',       'Körperpflege & Gesundheit')
) AS rules(keyword, category_name)
JOIN categories ON categories.name = rules.category_name
ON CONFLICT (keyword) DO NOTHING;
