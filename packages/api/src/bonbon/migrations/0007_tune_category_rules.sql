-- More keyword rules, tuned against the real Migros receipt (tests/data/textract_migros.json)
-- for issue #24. Raises item recognition on that receipt from 58 % to 95 %. Mostly brand and
-- product-line names Textract returns verbatim (Ragusa, Twist, Bon Chef, Nivea, Cantadou) plus
-- a few Swiss product words. 0006 is already applied, so these go in a new file.
--
-- Same mechanics as 0006: lowercase keyword, matched against the lowercased item name; the match
-- ending furthest right wins (categorize() in bonbon/receipts/categories.py). keyword is UNIQUE,
-- so ON CONFLICT keeps the seed idempotent. A few long keywords exist only to beat a shorter one
-- that would otherwise win on the right (e.g. 'gallenseife' beats 'seife', 'milcher' beats
-- 'milch', 'bratensauce' beats 'bon chef').

INSERT INTO category_rules (keyword, category_id)
SELECT keyword, categories.id
FROM (VALUES
    -- Süsswaren & Snacks (brands / product lines)
    ('ragusa',        'Süsswaren & Snacks'),
    ('branches',      'Süsswaren & Snacks'),
    ('twist',         'Süsswaren & Snacks'),
    ('vermicelles',   'Süsswaren & Snacks'),
    ('vernicelles',   'Süsswaren & Snacks'),  -- Textract also reads it with an 'n'
    ('milcher',       'Süsswaren & Snacks'),  -- 'Puffreis Milcher' = milk chocolate, beats 'milch'
    -- Brot & Backwaren
    ('crémecornet',   'Brot & Backwaren'),     -- fresh patisserie, beats 'cornet'
    -- Tiefkühl & Konserven
    ('bon chef',      'Tiefkühl & Konserven'),  -- ready-meal line (soups etc.)
    ('spinat',        'Tiefkühl & Konserven'),
    ('apfelmus',      'Tiefkühl & Konserven'),  -- fruit in a jar/can
    -- Fleisch & Fisch
    ('mostmöckli',    'Fleisch & Fisch'),
    -- Milchprodukte & Eier
    ('cantadou',      'Milchprodukte & Eier'),
    -- Getränke
    ('ice coffee',    'Getränke'),
    -- Grundnahrungsmittel (cooking staples: spice mixes, dry sauces, sugar)
    ('curry',         'Grundnahrungsmittel'),
    ('bratensauce',   'Grundnahrungsmittel'),   -- dry sauce powder, beats 'bon chef'
    ('kristallzucker', 'Grundnahrungsmittel'),
    ('kristallzucken', 'Grundnahrungsmittel'),  -- common Textract misread of 'Kristallzucker'
    -- Früchte & Gemüse
    ('amandine',      'Früchte & Gemüse'),       -- potato variety
    -- Haushalt & Reinigung
    ('comfort',       'Haushalt & Reinigung'),   -- fabric softener
    ('gallenseife',   'Haushalt & Reinigung'),   -- laundry stain remover, beats 'seife'
    -- Körperpflege & Gesundheit
    ('nivea',         'Körperpflege & Gesundheit')
) AS rules(keyword, category_name)
JOIN categories ON categories.name = rules.category_name
ON CONFLICT (keyword) DO NOTHING;
