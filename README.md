# Loop

Intake game for collecting what baby gear parents have, and what they're done with.

- **Categories** live in the Loop Google Sheet, Categories tab: one row per kind of gear, in deck order, with three "hero" versions (name + photo link) each. Anything in `hide` drops the row. `intake_only` marks categories we count but don't transact yet.
- **The game:** category card (Nope / Got one) → "Which one?" photo grid (3 heroes + Something else) → status check (Still using it / Taking up space / Saving it for baby #2). Email after card 3; first name, baby's birthday/due date and neighborhood after the last card.
- **Answers** land in the same Sheet: Responses (one row per player, saved from the email screen on, so partial plays count) and Swipes (one row per category answered).
- **The site rebuilds** every night, on changes to `builder/`, or right away from Actions → Build Loop deck → Run workflow. Hero photos are downloaded into `img/`; if one fails, the last good copy is kept. Each run's summary lists anything to fix.

`builder/Code.gs` is a copy of the Sheet's Apps Script, for reference. The "Add to Loop" key is replaced with `KEY_HERE`; the real one lives only in the Sheet's script editor.
`builder/categories.csv` is the fallback the build uses when `LOOP_SHEET_URL` isn't set.

### Toy age tiles
The Outgrown toys card shows a 3-toy collage for each age. The links live in the
`option_photos` column of the Categories tab: one group per age (same order as
`options`), groups separated by `|`, links inside a group separated by spaces.
To check new photos before using them, put `id url` lines in
`builder/tools/photo_candidates.txt` and run the **Photo check** workflow; it
pushes a contact sheet to the `photo-check` branch.
