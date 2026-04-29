#!/usr/bin/env python3
"""
AIA 卓達智悅基金資料自動更新腳本
- 用 Playwright headless Chrome 開 AIA 投資選擇頁
- 揀「卓達智悅」, 抓取所有 USD Z 字頭基金最新價格
- 嘗試從每隻基金嘅「現金股息派發記錄」攞最新派息, 計算年度化派息率
- 更新 data/funds.json
- 由 .github/workflows/update-funds.yml 每星期日凌晨呼叫
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNDS_FILE = REPO_ROOT / "data" / "funds.json"
AIA_URL = "https://www.aia.com.hk/zh-hk/help-and-support/individuals/investment-information/investment-options-prices.html"
PRODUCT_CODE = "TMP"  # 卓達智悅


def hk_now():
    """香港時區 ISO timestamp"""
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def scrape_aia_prices() -> dict:
    """攞 AIA 主頁所有 USD Z 字頭基金嘅最新價格"""
    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-HK",
        )
        page = context.new_page()
        print(f"[{hk_now()}] 開啟 AIA 投資選擇頁...")
        page.goto(AIA_URL, wait_until="networkidle", timeout=60000)

        # 揀「卓達智悅」(TMP)
        print(f"[{hk_now()}] 切換到 '卓達智悅' (TMP)...")
        page.select_option("select", PRODUCT_CODE)
        page.click("button:has-text('搜尋')")
        page.wait_for_timeout(4000)
        page.wait_for_selector("table tr td", state="visible", timeout=30000)

        # 抓取表格資料
        print(f"[{hk_now()}] 解析基金表格...")
        rows = page.locator("table").first.locator("tr").all()
        last_price_date = None

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
                    continue  # 只要 USD 基金
                price = float(m.group(2))

                date_text = cells[5].inner_text().strip()
                if date_text and not last_price_date:
                    last_price_date = date_text

                result[code] = {"newPrice": price}
                print(f"  ✓ {code}: USD {price:.4f}")
            except Exception as e:
                print(f"  ✗ Row error: {e}")

        browser.close()

    return {"funds": result, "lastPriceDate": last_price_date}


def scrape_dividend_records(codes: list) -> dict:
    """嘗試攞每隻基金最新月份嘅派息金額 (從 '現金股息派發記錄' 連結)
    回傳: { code: latestDividend or None }
    呢部份較複雜, 失敗就跳過 (保留現有 annYield)"""
    # 注意: AIA 嘅派息記錄頁係 popup / iframe, 結構複雜
    # 第一版先 skip 呢部份, 由用戶手動更新 annYield
    # 第二版可以加入 sub-page scraping
    return {}


def main():
    print(f"\n{'='*60}")
    print(f"  AIA Fund Auto-Update | {hk_now()}")
    print(f"{'='*60}\n")

    # Load existing config
    if not FUNDS_FILE.exists():
        print(f"❌ {FUNDS_FILE} 唔存在")
        sys.exit(1)

    with open(FUNDS_FILE, encoding="utf-8") as f:
        config = json.load(f)

    # Scrape latest prices
    try:
        scraped = scrape_aia_prices()
    except Exception as e:
        print(f"❌ Scraping 失敗: {e}")
        sys.exit(1)

    if not scraped["funds"]:
        print("❌ 抓唔到任何基金, 中止更新")
        sys.exit(1)

    # Update prices in config
    updated = []
    skipped = []
    for code, data in scraped["funds"].items():
        if code in config["funds"]:
            old_price = config["funds"][code].get("newPrice")
            new_price = data["newPrice"]
            if old_price != new_price:
                config["funds"][code]["newPrice"] = new_price
                config["funds"][code]["_lastPriceUpdate"] = hk_now()
                updated.append(f"{code}: {old_price} → {new_price}")
            else:
                skipped.append(code)
        else:
            print(f"⚠️  {code} 唔喺 config (新基金?), 跳過")

    # Update metadata
    config["lastUpdated"] = hk_now()
    if scraped.get("lastPriceDate"):
        config["lastPriceDate"] = scraped["lastPriceDate"]

    # Write back
    with open(FUNDS_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"  📊 更新總結")
    print(f"{'='*60}")
    print(f"✓ 更新: {len(updated)} 隻基金")
    for u in updated:
        print(f"   {u}")
    print(f"○ 無變化: {len(skipped)} 隻 ({', '.join(skipped) if skipped else '冇'})")
    print(f"📅 最新評估日: {config.get('lastPriceDate', 'N/A')}")
    print(f"🕐 更新時間: {config['lastUpdated']}")
    print(f"\n✅ 完成! 寫入 {FUNDS_FILE}\n")


if __name__ == "__main__":
    main()
