"""
Scrapes the Amazon wishlist and generates items.json + data.js for the website.

Usage:
    uv run python raw/projects/amazon-affiliate/scrape.py

Output:
    raw/projects/amazon-affiliate/items.json  — raw data
    raw/projects/amazon-affiliate/data.js     — embeddable JS for index.html
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

WISHLIST_URL = "https://www.amazon.com.br/hz/wishlist/ls/LIURBM0F2X58"
ASSOCIATE_TAG = "guilhermefsp-20"
HERE = Path(__file__).parent


async def scrape_wishlist() -> list[dict]:
    items = []

    async with async_playwright() as p:
        # Use system Edge (pre-installed on Windows 10) — no browser download needed
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        )
        # Hide automation flag
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        print(f"Loading: {WISHLIST_URL}")
        await page.goto(WISHLIST_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        page_num = 1
        seen_asins: set[str] = set()

        # Check total item count from the page header if available
        try:
            count_el = await page.query_selector("#listSummary, .wl-list-info, [id*='itemCount']")
            if count_el:
                print(f"  List info: {(await count_el.inner_text()).strip()}")
        except Exception:
            pass

        while True:
            print(f"  Page {page_num} — ", end="", flush=True)

            # Scroll incrementally to trigger infinite-scroll / lazy loading
            prev_item_count = len(seen_asins)
            prev_height = -1
            for _ in range(15):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1200)
                height = await page.evaluate("document.body.scrollHeight")
                if height == prev_height:
                    break
                prev_height = height

            # Also click any "load more" / "show more" buttons
            for load_sel in [
                "input[name='submit.addToCart']",
                "button:has-text('Mostrar mais')",
                "a:has-text('Mostrar mais')",
                "#endOfListMarker ~ * button",
                "[data-action='load-more-items'] button",
            ]:
                try:
                    btn = await page.query_selector(load_sel)
                    if btn and await btn.is_visible():
                        print(f"  Clicking load-more: {load_sel}")
                        await btn.click()
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass

            await page.evaluate("window.scrollTo(0, 0)")

            # Wait for at least one item link
            try:
                await page.wait_for_selector(
                    "a.a-link-normal[href*='/dp/']", timeout=10000
                )
            except Exception:
                print("no items found, stopping.")
                break

            # Extract all item links on this page
            links = await page.query_selector_all("a.a-link-normal[href*='/dp/']")
            page_count = 0

            for link in links:
                href = await link.get_attribute("href") or ""
                m = re.search(r"/dp/([A-Z0-9]{10})", href)
                if not m:
                    continue
                asin = m.group(1)
                if asin in seen_asins:
                    continue
                seen_asins.add(asin)

                title = (await link.get_attribute("title") or "").strip()

                # Walk up to the li to get image and price
                image = ""
                price = ""
                try:
                    li = await link.evaluate_handle(
                        "el => el.closest('li') || el.closest('[data-id]')"
                    )
                    if li:
                        # Image lives at li level (class wl-img-size-adjust), not inside the link
                        img = await li.query_selector("img.wl-img-size-adjust, img[alt]")
                        if img:
                            image = await img.get_attribute("src") or ""
                            if not title:
                                title = (await img.get_attribute("alt") or "").strip()

                        for sel in [
                            ".a-price .a-offscreen",
                            ".a-color-price",
                            ".itemUsedAndNewPrice",
                        ]:
                            price_el = await li.query_selector(sel)
                            if price_el:
                                price = (await price_el.inner_text()).strip()
                                if price:
                                    break
                except Exception:
                    pass

                affiliate_url = (
                    f"https://www.amazon.com.br/dp/{asin}/?tag={ASSOCIATE_TAG}"
                )

                items.append(
                    {
                        "title": title,
                        "asin": asin,
                        "image": image,
                        "price": price,
                        "affiliate_url": affiliate_url,
                    }
                )
                page_count += 1

            print(f"{page_count} items (total: {len(items)})")

            # Try every known next-page pattern for Amazon.com.br wishlists
            next_btn = None
            for sel in [
                "li.a-last:not(.a-disabled) a",
                "ul.a-pagination li.a-last:not(.a-disabled) a",
                "a[aria-label*='próxima' i]",
                "a[aria-label*='next' i]",
                ".a-pagination .a-last:not(.a-disabled) a",
            ]:
                next_btn = await page.query_selector(sel)
                if next_btn:
                    break

            # Text-based fallback — scan all <a> tags, no timeout
            if not next_btn:
                for a in await page.query_selector_all("a"):
                    try:
                        text = (await a.inner_text()).strip().lower()
                        if text in ("próxima", "next", "próxima página", ">"):
                            next_btn = a
                            break
                    except Exception:
                        continue

            if not next_btn:
                # Debug: show what pagination HTML looks like
                pag = await page.query_selector(".a-pagination")
                if pag:
                    print(f"  Pagination HTML: {await pag.inner_html()}")
                else:
                    print("  No pagination element found — done.")
                break

            await next_btn.scroll_into_view_if_needed()
            await next_btn.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(2000)
            page_num += 1

        await browser.close()

    return items


def write_outputs(items: list[dict]) -> None:
    json_path = HERE / "items.json"
    json_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nSaved {len(items)} items → {json_path}")

    js_path = HERE / "data.js"
    js_path.write_text(
        f"// Auto-generated by scrape.py — do not edit manually\n"
        f"const ITEMS = {json.dumps(items, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )
    print(f"Saved JS data  → {js_path}")


async def main() -> None:
    items = await scrape_wishlist()
    if not items:
        print("No items scraped — check if the wishlist URL is correct.", file=sys.stderr)
        sys.exit(1)
    write_outputs(items)


if __name__ == "__main__":
    asyncio.run(main())
