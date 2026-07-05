"""One-off diagnostic: saves the real rendered sgcarmart search page's HTML
locally so its actual CSS structure can be inspected, since the selectors
in credit_approver/valuation.py have never been verified against live
markup.

Run with:
    python scripts/inspect_sgcarmart.py
"""
from playwright.sync_api import sync_playwright

URL = "https://www.sgcarmart.com/used-cars/listing?q=toyota+corolla&avl=&page=1"
OUTPUT_PATH = "sgcarmart_rendered.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, timeout=30_000)
    page.wait_for_timeout(5_000)  # let client-side rendering settle
    html = page.content()
    page.screenshot(path="sgcarmart_screenshot.png", full_page=True)
    browser.close()

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Saved rendered HTML to {OUTPUT_PATH} ({len(html)} chars)")
print("Saved a screenshot to sgcarmart_screenshot.png")
