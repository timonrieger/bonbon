# Glossary

Code and docs use the English term. UI text uses the German one.

| German (UI, proposal) | English (code) | Meaning |
|---|---|---|
| Kassenzettel, Beleg | receipt | One uploaded photo/PDF and the data extracted from it |
| Artikel, Position | item | One line on a receipt (name, quantity, price, category) |
| Händler, Laden | store | Migros, Coop, Aldi, Lidl |
| Kategorie | category | Fixed list, e.g. Milchprodukte → `dairy` |
| Haushalt | household | Group of users sharing receipts and the dashboard |
| Mitglied | member | A user in a household; role `owner` or `member` |
| Einladungscode | invite code | One-time code to join a household, valid 48 h |
| Monatswerte | monthly totals | Pre-computed sums per month, category and store |
| Status: hochgeladen / in Bearbeitung / fertig / fehlgeschlagen / Duplikat | `uploaded` / `processing` / `done` / `failed` / `duplicate` | Receipt processing status |
| Kontolöschung | account deletion | Deleting a user and their data |
| Texterkennung | extraction | Textract AnalyzeExpense (or AI API fallback) |
