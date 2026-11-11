# Loop

Swipe game for collecting what baby gear parents have, and what they're ready to pass on.

- **Products** live in the Loop Google Sheet, Products tab. Paste a product page link and a category; the build fills in the photo, name, price and blurb.
- **Answers** land in the same Sheet (Responses and Swipes tabs).
- **The site rebuilds** every night, or right away from Actions → Build Loop deck → Run workflow. Each run's summary lists products that came out without a photo or price.

`builder/Code.gs` is a copy of the Sheet's Apps Script, for reference.
