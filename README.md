# Rice Student Lookup

A lookup tool for Rice University's public student directory. Search by
name (with typo-tolerant "did you mean" suggestions), or browse/filter by
college, class year, school/division, and major — including double majors
and students who haven't declared a specific major yet.

Matriculation year and email are intentionally not shown or published;
see [docs/needs_review.csv](docs/needs_review.csv) for the handful of
majors the automated classifier couldn't confidently place.

## Live site

Served from `docs/` via GitHub Pages — see the repo's **About** section
for the link (enabled after the first Pages deploy).

## Structure

- `rice_scraper/` — scrapes Rice's public directory pages into
  `rice_scraper/data/rice_people.csv` (source of truth). Email addresses
  are stripped from everything in this repo.
- `docs/build_data.py` — parses the CSV, splits combined major fields
  (e.g. "Computer Science Linguistics") into individual majors, and maps
  each to its official Rice school/division, producing `docs/data.js`.
- `docs/index.html` — the lookup UI itself: a static page with the
  dataset embedded, so it needs no backend or build step.

## Regenerating the data

```
python3 docs/build_data.py
```
