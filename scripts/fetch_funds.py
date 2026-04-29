#!/usr/bin/env python3
"""
AIA 卓達智悅基金資料自動更新腳本 (v3 - 多策略 click)
"""
import json
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNDS_FILE = REPO_ROOT / "data" / "funds.json"
SCREENSHOT = REPO_ROOT / "scripts" / "_debug_screenshot.png"
HTML_DUMP = REPO_ROOT / "scripts" / "_debug_page.html"
AIA_URL = "https://www.aia.com.hk/zh-hk/help-and-support/individuals/investment-information/investment-options-prices.html"
PRODUCT_CODE = "TMP"


def hk_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def robust_click(page, selector: str, label: str = ""):
    """嘗試多種策略 click 一個 element, 直到成功"""
    print(f"  [click] {label or selector}")
    locator = page.locator(selector)
    count = locator.count()
    print(f"    搵到 {count} 個 element")

    if count == 0:
        raise RuntimeError(f"完全搵唔到 {selector}")

    # Strategy 1: 揀 visible + 自然 click
    for i in range(count):
        el = locator.nth(i)
        try:
            if el.is_visible():
                el.click(timeout=8000)
                print(f"    ✓ Strategy 1 (visible click) 成功 [index {i}]")
                return True
        except Exception as e:
            print(f"    ✗ Strategy 1 [index {i}]: {type(e).__name__}")

    # Strategy 2: scroll into view + force click
    for i in range(count):
        el = locator.nth(i)
        try:
            el.scroll_into_view_if_needed(timeout=5000)
            el.click(force=True, timeout=8000)
            print(f"    ✓ Strategy 2 (force click + scroll) 成功 [index {i}]")
            return True
        except Exception as e:
            print(f"    ✗ Strategy 2 [index {i}]: {type(e).__name__}: {e}")

    # Strategy 3: dispatch click event via JS
    for i in range(count):
        try:
            el = locator.nth(i)
            el.dispatch_event("click")
            print(f"    ✓ Strategy 3 (dispatch event) 成功 [index {i}]")
            return True
        except Exception as e:
            print(f"    ✗ Strategy 3 [index {i}]: {type(e).__name__}")

    # Strategy 4: direct JS click via page.evaluate
    try:
        result = page.evaluate(f"""
            () => {{
                const els = document.querySelectorAll({json.dumps(selector)});
                if (els.length === 0) return 'no elements';
                els[els.length - 1].click();
                return 'clicked element ' + (els.length - 1);
            }}
        """)
        print(f"    ✓ Strategy 4 (raw JS click): {result}")
        return True
    except Exception as e:
        print(f"    ✗ Strategy 4: {e}")

    raise RuntimeError(f"4 種 strategies 全部失敗: {label or selector}")


def select_visible(page, selector: str, value: str, label: str = ""):
    """喺 visible 嘅 <select> 揀 option"""
    locator = page.locator(selector)
    count = locator.count()
    print(f"  [select] {label or selector}: 搵到 {count} 個")
    for i in range(count):
        el = locator.nth(i)
        try:
            if el.is_visible():
                el.select_option(value)
                print(f"    ✓ 揀 '{value}' [index {i}]")
                return
        except Exception:
            continue
    # Fallback: 直接 set value via JS
    page.evaluate(f"""
        () => {{
            const sels = document.querySelectorAll({json.dumps(selector)});
            for (const s of sels) {{
                for (const opt of s.options) {{
                    if (opt.value === {json.dumps(value)}) {{
                        s.value = {json.dumps(value)};
                        s.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return 'set via JS';
                    }}
                }}
            }}
            return 'no match';
        }}
    """)
    print(f"    ✓ Fallback: JS set value '{value}'")


def scrape_aia_prices() -> dict:
    result = {}
    last_price_date = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-HK",
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            print(f"[{hk_now()}] 開啟 AIA 投資選擇頁...")
            page.goto(AIA_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)  # 多等下確保 JS 完全 init

            # Cookie banner
            for sel in ["button:has-text('接受')", "button:has-text('Accept')", "button:has-text('關閉')"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1500):
                        btn.click(timeout=3000)
                        print(f"  ✓ 關 popup: {sel}")
                        page.wait_for_timeout(500)
                except Exception:
                    pass

            # 揀產品
            print(f"[{hk_now()}] 揀 '卓達智悅' (TMP)...")
            select_visible(page, "select", PRODUCT_CODE, "產品 dropdown")
            page.wait_for_timeout(800)

            # 點搜尋
            print(f"[{hk_now()}] 點'搜尋'按鈕...")
            robust_click(page, "button.go-btn", "搜尋按鈕")
            page.wait_for_timeout(5000)

            # 等 table 出現
            print(f"[{hk_now()}] 等基金表格...")
            page.wait_for_selector("table tbody tr", state="visible", timeout=30000)
            page.wait_for_timeout(2000)

            # 解析
            print(f"[{hk_now()}] 解析基金表格...")
            rows = page.locator("table").first.locator("tr").all()

            for row in rows:
                try:
                    cells = row.locator("td").all()
                    if len(cells) < 6:
                        continue
                    code = cells[1].inner_text().strip()
                    if not code.startswith("Z"):
                        continue
                    price_text = cells[3].inner_text().strip().replace(" ", "")
                    m = re.search(r"(美元|港元|歐元|英鎊|人民幣)([\d.]+)", price_text)
                    if not m or m.group(1) != "美元":
                        continue
                    price = float(m.group(2))
                    if not last_price_date:
                        date_text = cells[5].inner_text().strip()
                        if date_text:
                            last_price_date = date_text
                    result[code] = price
                    print(f"  ✓ {code}: USD {price:.4f}")
                except Exception as e:
                    pass

        except Exception as e:
            print(f"\n❌ Scraping 過程出錯: {e}")
            traceback.print_exc()
            try:
                page.screenshot(path=str(SCREENSHOT), full_page=True)
                print(f"📸 Screenshot: {SCREENSHOT}")
            except Exception:
                pass
            try:
                html = page.content()
                with open(HTML_DUMP, "w", encoding="utf-8") as f:
                    f.write(html[:200000])  # 頭 200KB
                print(f"📄 HTML dump: {HTML_DUMP}")
            except Exception:
                pass
            browser.close()
            raise

        browser.close()

    return {"funds": result, "lastPriceDate": last_price_date}


def main():
    print(f"\n{'='*60}\n  AIA Fund Auto-Update | {hk_now()}\n{'='*60}\n")

    if not FUNDS_FILE.exists():
        print(f"❌ {FUNDS_FILE} 唔存在")
        sys.exit(1)
    with open(FUNDS_FILE, encoding="utf-8") as f:
        config = json.load(f)

    try:
        scraped = scrape_aia_prices()
    except Exception as e:
        print(f"\n❌ 抓取失敗: {e}")
        sys.exit(1)

    if not scraped["funds"]:
        print("❌ 抓唔到任何基金")
        sys.exit(1)

    updated, skipped = [], []
    for code, new_price in scraped["funds"].items():
        if code in config["funds"]:
            old_price = config["funds"][code].get("newPrice")
            if old_price != new_price:
                config["funds"][code]["newPrice"] = new_price
                config["funds"][code]["_lastPriceUpdate"] = hk_now()
                updated.append(f"{code}: {old_price} → {new_price}")
            else:
                skipped.append(code)

    config["lastUpdated"] = hk_now()
    if scraped.get("lastPriceDate"):
        config["lastPriceDate"] = scraped["lastPriceDate"]

    with open(FUNDS_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 更新: {len(updated)} 隻")
    for u in updated: print(f"   {u}")
    print(f"○ 無變化: {len(skipped)} 隻")
    print(f"📅 評估日: {config.get('lastPriceDate', 'N/A')}")
    print(f"\n✅ 完成!\n")


if __name__ == "__main__":
    main()
