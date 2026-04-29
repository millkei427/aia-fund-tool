#!/usr/bin/env python3
"""
AIA 卓達智悅基金資料自動更新腳本
- 用 Playwright headless Chrome 開 AIA 投資選擇頁
- 揀「卓達智悅」, 抓取所有 USD Z 字頭基金最新價格
- 更新 data/funds.json
- 由 .github/workflows/update-funds.yml 每星期日凌晨呼叫
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
AIA_URL = "https://www.aia.com.hk/zh-hk/help-and-support/individuals/investment-information/investment-options-prices.html"
PRODUCT_CODE = "TMP"


def hk_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def click_visible(page, selector: str, label: str = ""):
    """Click first VISIBLE matching element (handles desktop+mobile dupes)"""
    locator = page.locator(selector)
    count = locator.count()
    print(f"  [click] {label or selector}: 搵到 {count} 個 element")
    for i in range(count):
        el = locator.nth(i)
        try:
            if el.is_visible():
                el.click(timeout=10000)
                print(f"  ✓ 點咗 visible 果個 (index {i})")
                return True
        except Exception as e:
            print(f"  ⚠️  index {i} click 失敗: {e}")
            continue
    raise RuntimeError(f"冇 visible 嘅 {label or selector}")


def select_visible(page, selector: str, value: str, label: str = ""):
    """Select option on first VISIBLE matching <select>"""
    locator = page.locator(selector)
    count = locator.count()
    print(f"  [select] {label or selector}: 搵到 {count} 個 element")
    for i in range(count):
        el = locator.nth(i)
        try:
            if el.is_visible():
                el.select_option(value)
                print(f"  ✓ Select '{value}' 喺 visible 果個 (index {i})")
                return True
        except Exception as e:
            print(f"  ⚠️  index {i} select 失敗: {e}")
            continue
    raise RuntimeError(f"冇 visible 嘅 {label or selector}")


def scrape_aia_prices() -> dict:
    """攞 AIA 主頁所有 USD Z 字頭基金嘅最新價格"""
    result = {}
    last_price_date = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-HK",
            viewport={"width": 1440, "height": 900},  # 用 desktop viewport 避免 mobile menu
        )
        page = context.new_page()

        try:
            print(f"[{hk_now()}] 開啟 AIA 投資選擇頁...")
            page.goto(AIA_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)  # 等 JS 渲染

            # 試下 dismiss cookie banner / popup (如有)
            for sel in ["button:has-text('接受')", "button:has-text('Accept')", "button:has-text('關閉')"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click(timeout=5000)
                        print(f"  ✓ 關閉 popup: {sel}")
                        page.wait_for_timeout(500)
                except Exception:
                    pass

            # 揀「卓達智悅」(TMP) - 用 visible filter
            print(f"[{hk_now()}] 切換到 '卓達智悅' (TMP)...")
            select_visible(page, "select", PRODUCT_CODE, "產品 dropdown")
            page.wait_for_timeout(500)

            # 點搜尋按鈕 - 用 visible filter (重點修正)
            print(f"[{hk_now()}] 點'搜尋'按鈕...")
            click_visible(page, "button.go-btn", "搜尋按鈕")
            page.wait_for_timeout(4000)

            # 等 table 出現
            print(f"[{hk_now()}] 等基金表格載入...")
            page.wait_for_selector("table tbody tr", state="visible", timeout=30000)
            page.wait_for_timeout(1500)

            # 抓取
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
                    print(f"  ✗ Row error: {e}")

        except Exception as e:
            print(f"❌ Scraping 過程出錯: {e}")
            traceback.print_exc()
            try:
                page.screenshot(path=str(SCREENSHOT), full_page=True)
                print(f"📸 Debug screenshot: {SCREENSHOT}")
            except Exception:
                pass
            browser.close()
            raise

        browser.close()

    return {"funds": result, "lastPriceDate": last_price_date}


def main():
    print(f"\n{'='*60}")
    print(f"  AIA Fund Auto-Update | {hk_now()}")
    print(f"{'='*60}\n")

    if not FUNDS_FILE.exists():
        print(f"❌ {FUNDS_FILE} 唔存在")
        sys.exit(1)

    with open(FUNDS_FILE, encoding="utf-8") as f:
        config = json.load(f)

    try:
        scraped = scrape_aia_prices()
    except Exception as e:
        print(f"❌ Scraping 失敗: {e}")
        sys.exit(1)

    if not scraped["funds"]:
        print("❌ 抓唔到任何基金, 中止更新")
        sys.exit(1)

    updated, skipped, missing = [], [], []
    for code, new_price in scraped["funds"].items():
        if code in config["funds"]:
            old_price = config["funds"][code].get("newPrice")
            if old_price != new_price:
                config["funds"][code]["newPrice"] = new_price
                config["funds"][code]["_lastPriceUpdate"] = hk_now()
                updated.append(f"{code}: {old_price} → {new_price}")
            else:
                skipped.append(code)
        else:
            missing.append(code)

    config["lastUpdated"] = hk_now()
    if scraped.get("lastPriceDate"):
        config["lastPriceDate"] = scraped["lastPriceDate"]

    with open(FUNDS_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"  📊 更新總結")
    print(f"{'='*60}")
    print(f"✓ 更新: {len(updated)} 隻")
    for u in updated:
        print(f"   {u}")
    print(f"○ 無變化: {len(skipped)} 隻")
    if missing:
        print(f"⚠️  config 冇: {', '.join(missing)}")
    print(f"📅 評估日: {config.get('lastPriceDate', 'N/A')}")
    print(f"🕐 更新時間: {config['lastUpdated']}")
    print(f"\n✅ 完成!\n")


if __name__ == "__main__":
    main()
