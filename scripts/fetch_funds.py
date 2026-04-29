#!/usr/bin/env python3
"""
AIA 卓達智悅基金資料自動更新腳本 (v4 - URL param + table-first)
策略:
  1. 嘗試用 URL parameter ?product=TMP 直接 filter
  2. 即使 filter 唔成功, 都掃整張 table 攞所有 Z-prefix USD 基金
  3. AIA 個 table 可能本身就 list 晒所有產品共用嘅基金
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


def hk_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def parse_table_rows(page, expected_codes: set) -> dict:
    """掃 page 上面所有 <tr>, 抽 Z-prefix USD 基金"""
    result = {}
    last_date = None

    # 攞所有 tr (不限於某個 table)
    rows = page.locator("tr").all()
    print(f"  搵到 {len(rows)} 個 <tr>")

    for row in rows:
        try:
            cells = row.locator("td").all()
            if len(cells) < 6:
                continue
            code = cells[1].inner_text().strip()
            if not code or not code.startswith("Z"):
                continue
            price_text = cells[3].inner_text().strip().replace(" ", "")
            m = re.search(r"(美元|港元|歐元|英鎊|人民幣)([\d.]+)", price_text)
            if not m or m.group(1) != "美元":
                continue
            price = float(m.group(2))

            if not last_date and len(cells) > 5:
                date_text = cells[5].inner_text().strip()
                if re.match(r"^\d{2}/\d{2}/\d{4}$", date_text):
                    last_date = date_text

            # 唔重複加 (有可能同一 code 出現喺多個 row, 例如 USD + RMB 對沖版本)
            if code not in result:
                result[code] = price
                marker = "✓" if code in expected_codes else "+"
                print(f"  {marker} {code}: USD {price:.4f}")
        except Exception:
            pass

    return {"funds": result, "lastPriceDate": last_date}


def scrape_aia_prices(expected_codes: set) -> dict:
    """用兩種策略嘗試攞 AIA 數據"""
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
            # === 策略 1: 直接 navigate 到 default page ===
            print(f"[{hk_now()}] 策略 1: 開啟 default page (預設 TMP2)")
            page.goto(AIA_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(6000)  # 等 Angular fully render

            # 關 popup
            for sel in ["button:has-text('接受')", "button:has-text('Accept')",
                        "button:has-text('關閉')", "button[aria-label='Close']"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1500):
                        btn.click(timeout=3000)
                        print(f"  ✓ 關 popup: {sel}")
                        page.wait_for_timeout(500)
                except Exception:
                    pass

            # 等 table populate
            try:
                page.wait_for_selector("table tr td", timeout=20000)
                print(f"  ✓ Table 已載入")
            except Exception:
                print(f"  ⚠️  等 table 超時, 試下繼續...")

            page.wait_for_timeout(2000)
            print(f"[{hk_now()}] 嘗試解析 default page 表格...")
            data = parse_table_rows(page, expected_codes)

            # 計命中率
            hit = len(set(data["funds"].keys()) & expected_codes)
            total = len(expected_codes)
            print(f"\n  📊 策略 1 命中: {hit}/{total} 個預期基金")

            # 如果命中率 < 50%, 試策略 2
            if hit < total * 0.5:
                print(f"\n[{hk_now()}] 策略 2: 用 JS 直接設 dropdown + 觸發 Angular change")
                try:
                    # 用 JS 直接 set dropdown value 同 trigger 全部相關 events
                    page.evaluate("""
                        () => {
                            const sels = document.querySelectorAll('select');
                            for (const s of sels) {
                                for (const opt of s.options) {
                                    if (opt.value === 'TMP') {
                                        s.value = 'TMP';
                                        // Trigger 所有可能 events
                                        s.dispatchEvent(new Event('input', { bubbles: true }));
                                        s.dispatchEvent(new Event('change', { bubbles: true }));
                                        // Angular forms may need this
                                        if (window.ng) {
                                            try { window.ng.applyChanges?.(s); } catch(e){}
                                        }
                                        break;
                                    }
                                }
                            }
                            // 嘗試所有可能 search button + 直接 call onclick
                            const btns = document.querySelectorAll('button.go-btn, button[type="submit"]');
                            for (const b of btns) {
                                try { b.click(); } catch(e) {}
                                if (b.onclick) try { b.onclick(); } catch(e) {}
                            }
                            return 'done';
                        }
                    """)
                    page.wait_for_timeout(8000)  # 等 AJAX
                    print(f"[{hk_now()}] 策略 2 完成,重新解析表格...")
                    data2 = parse_table_rows(page, expected_codes)
                    hit2 = len(set(data2["funds"].keys()) & expected_codes)
                    print(f"  📊 策略 2 命中: {hit2}/{total}")
                    if hit2 > hit:
                        data = data2
                        hit = hit2
                except Exception as e:
                    print(f"  ⚠️  策略 2 失敗: {e}")

            if hit == 0:
                print(f"\n❌ 兩個策略都攞唔到任何預期基金")
                page.screenshot(path=str(SCREENSHOT), full_page=True)
                with open(HTML_DUMP, "w", encoding="utf-8") as f:
                    f.write(page.content()[:200000])
                print(f"📸 Screenshot + HTML dump saved")
                raise RuntimeError("Cannot extract any expected fund data")

            return data

        except Exception as e:
            print(f"\n❌ Scraping 出錯: {e}")
            traceback.print_exc()
            try:
                page.screenshot(path=str(SCREENSHOT), full_page=True)
                with open(HTML_DUMP, "w", encoding="utf-8") as f:
                    f.write(page.content()[:200000])
                print(f"📸 Debug files saved")
            except Exception:
                pass
            raise
        finally:
            browser.close()


def main():
    print(f"\n{'='*60}\n  AIA Fund Auto-Update v4 | {hk_now()}\n{'='*60}\n")

    if not FUNDS_FILE.exists():
        print(f"❌ {FUNDS_FILE} 唔存在")
        sys.exit(1)
    with open(FUNDS_FILE, encoding="utf-8") as f:
        config = json.load(f)
    expected = set(config["funds"].keys())
    print(f"📋 預期基金: {len(expected)} 隻 ({', '.join(sorted(expected)[:6])}...)\n")

    try:
        scraped = scrape_aia_prices(expected)
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

    print(f"\n{'='*60}\n  ✅ 完成總結\n{'='*60}")
    print(f"✓ 更新: {len(updated)} 隻")
    for u in updated: print(f"   {u}")
    print(f"○ 無變化: {len(skipped)} 隻")
    print(f"📅 評估日: {config.get('lastPriceDate', 'N/A')}")
    print(f"🕐 更新時間: {config['lastUpdated']}\n")


if __name__ == "__main__":
    main()
