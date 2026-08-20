# lista-lili — Claude Instructions

**Project path:** `D:\The Brain\projects\lista-lili`

## Shell conventions

- Scripts use `Path(__file__).parent` for output paths — run from The Brain root with a relative path, no `cd` needed.
- Playwright uses system Edge (`channel="msedge"`) — no browser download required.

## Common commands

| Task | Command (from D:\The Brain) |
|------|---------|
| Run scraper | `uv run python projects/lista-lili/scrape.py` |
| Deploy | `git add projects/lista-lili/items.json projects/lista-lili/data.js && git commit -m "..." && git push` |
