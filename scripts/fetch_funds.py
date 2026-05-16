#!/usr/bin/env python3
"""
AIA 卓達智悅基金資料自動更新腳本 (v5 - 加派息 PDF 抓取)
策略:
  1. Playwright 爬 AIA 投資選擇頁面 → 攞每隻 Z 基金嘅最新價格
  2. 對每隻 Z 基金 download 派息 PDF → parse 最新一個月派息 + 年息率
     URL pattern: aia.com.hk/content/dam/hk/zh-hk/pdf/dividend-composition-and-distribution-record/{CODE}.pdf
  3. 寫入 data/funds.json：newPrice + latestDividendPerShare + latestYieldPct + dividendMonth
"""
import io
import json
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

try:
    import requests
    import pdfplumber
    PDF_OK = True
except ImportError:
    PDF_OK = False
    print("⚠️  pdfplumber/requests 未安裝, 跳過派息抓取 (只更新價格)")

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


DIVIDEND_PDF_URL = "https://www.aia.com.hk/content/dam/hk/zh-hk/pdf/dividend-composition-and-distribution-record/{code}.pdf"

# === 基金月報 URL discovery (Phase 1: Allianz only) ===
# Allianz 系列嘅「派息成分」PDF 冇 yield 欄, 需要去 fund detail 頁攞「基金月報」PDF URL
ALLIANZ_FUNDS = {"Z07", "Z08"}


def scrape_factsheet_urls(codes: set) -> dict:
    """用 Playwright 由 AIA detail 頁攞每隻 fund 嘅「基金月報」PDF URL"""
    if not codes:
        return {}
    print(f"\n[{hk_now()}] 攞 {len(codes)} 隻基金月報 URL: {sorted(codes)}")
    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-HK",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        try:
            page.goto(AIA_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(6000)
            for sel in ["button:has-text('接受')", "button:has-text('Accept')", "button[aria-label='Close']"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1500):
                        btn.click(timeout=3000); page.wait_for_timeout(500)
                except Exception:
                    pass
            page.wait_for_selector("table tr td", timeout=20000)
            page.wait_for_timeout(2000)
            rows = page.locator("tr").all()
            for code in sorted(codes):
                detail_href = None
                for row in rows:
                    try:
                        cells = row.locator("td").all()
                        if len(cells) > 1 and cells[1].inner_text().strip() == code:
                            # 揾「連繫基金詳情」link (通常係 td[7] 嗰個 chart icon)
                            for link in row.locator("a").all():
                                href = link.get_attribute("href")
                                if href and "details.html" in href:
                                    detail_href = href
                                    break
                            break
                    except Exception:
                        continue
                if not detail_href:
                    print(f"  ✗ {code}: 喺 prices 表搵唔到 detail link")
                    continue
                if detail_href.startswith("/"):
                    detail_href = "https://www.aia.com.hk" + detail_href
                # Navigate to detail page
                try:
                    page.goto(detail_href, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(4000)
                    # 揾 基金月報 link
                    href = None
                    for sel in ["a:has-text('基金月報')", "a[href*='monthly']", "a[href*='fact-sheet']", "a[href*='factsheet']"]:
                        try:
                            link = page.locator(sel).first
                            if link.count() > 0:
                                href = link.get_attribute("href")
                                if href: break
                        except Exception:
                            continue
                    if href:
                        if href.startswith("/"):
                            href = "https://www.aia.com.hk" + href
                        result[code] = href
                        print(f"  ✓ {code}: {href.split('/')[-1]}")
                    else:
                        print(f"  ✗ {code}: detail 頁冇基金月報 link")
                except Exception as e:
                    print(f"  ✗ {code}: navigate fail - {e}")
        finally:
            browser.close()
    return result


def parse_allianz_factsheet(pdf_bytes: bytes) -> dict | None:
    """Allianz 月報 parser: 揾「年度化股息收益率」第一個 data row
    PDF table 結構: 紀錄日 | 除息日 | 每股派息 | 除息日資產淨值 | 股息收益率 | 年度化股息收益率
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = ""
            for p in pdf.pages:
                t = p.extract_text()
                if t: text += t + "\n"
        # Allianz 行 pattern: DD/MM/YYYY DD/MM/YYYY <div> <NAV> <yield%> <annualized%>
        # eg: "13/03/2026 16/03/2026 0.05500 美元 8.2643 美元 0.67% 8.29%"
        # 揾第一個有兩個 dates 嘅 row
        for line in text.split("\n"):
            line = line.strip()
            if not line: continue
            dates = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", line)
            if len(dates) < 2:
                continue
            # 揾所有 percentage values, 最後一個應該係年度化
            pcts = re.findall(r"(\d{1,2}\.\d{1,2})\s*%", line)
            if len(pcts) < 2:  # 起碼要有 股息收益率 + 年度化
                continue
            annualized = float(pcts[-1])
            # dividend per share: 揾 0.0XXXX 或 0.XX
            divs = re.findall(r"(?<![\d.])(0\.\d{3,7})(?![\d.])", line)
            if not divs:
                continue
            div_val = float(divs[0])
            # 月份: 用第一個 date (紀錄日)
            mon_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            d, m, y = dates[0].split("/")
            try:
                month = mon_names[int(m)-1] + "-" + y[-2:]
            except (ValueError, IndexError):
                continue
            return {"month": month, "dividendPerShare": div_val, "yieldPct": annualized}
        return None
    except Exception as e:
        print(f"    ⚠️  Allianz parser error: {e}")
        return None


def fetch_factsheet_dividend(code: str, url: str) -> dict | None:
    """Download 基金月報 PDF + 用對應 parser 抽 yield"""
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        if code in ALLIANZ_FUNDS:
            return parse_allianz_factsheet(r.content)
        return None
    except Exception as e:
        print(f"    ⚠️  {code} factsheet fetch error: {e}")
        return None


def fetch_dividend(code: str) -> dict | None:
    """攞單一隻基金嘅最新派息. Returns {month, dividendPerShare, yieldPct} or None
    策略:
      1. 用 pdfplumber.extract_tables() 抽 table, 搵第一個 header 包含 'Yield'/'年息率' 嘅 table
      2. Fallback: regex match 任何「Mon-YY ... 0.xxxx ... NN.NN%」格式
      3. Fallback: regex match「Mon-YY ... 0.xxxx ... NN.NN」(冇 % 都得)
    """
    url = DIVIDEND_PDF_URL.format(code=code)
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        pdf_bytes = r.content
        # === Strategy 1: extract_tables ===
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables() or []
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    # 搵 header row + 優先揀「年度化」yield column (有啲 PDF 有兩個 yield 欄)
                    header_idx = -1
                    div_col = yld_col = month_col = -1
                    yld_priority = 999  # 1 = 年度化 (最好), 2 = 普通 yield
                    for i, row in enumerate(table[:3]):
                        cells = [str(c or "").strip() for c in row]
                        joined = " ".join(cells).lower()
                        if not ("yield" in joined or "息率" in joined):
                            continue
                        header_idx = i
                        for j, c in enumerate(cells):
                            cl = c.lower()
                            # Yield column 優先級：年度化 > 普通
                            p = 999
                            if "annualized" in cl or "年度化" in c:
                                p = 1
                            elif "yield" in cl or "年息率" in c or "息率" in c:
                                p = 2
                            if p < yld_priority:
                                yld_col = j; yld_priority = p
                            # Dividend column
                            if div_col < 0 and ("dividend" in cl or "每股派息" in c or "每股股息" in c or "派息" in c or "股息" in c):
                                div_col = j
                            # Month/date column
                            if month_col < 0 and ("month" in cl or "月份" in c or "紀錄日" in c or "记录日" in c or "record date" in cl):
                                month_col = j
                        break
                    if header_idx < 0:
                        continue
                    # 第一個 data row (latest)
                    for row in table[header_idx + 1:]:
                        cells = [str(c or "").strip() for c in row]
                        if not any(cells):
                            continue
                        # 抽月份 — 試兩種格式: Mon-YY (eg "Mar-26") 或 DD/MM/YYYY
                        month = ""
                        search_cells = [cells[month_col]] if (month_col >= 0 and month_col < len(cells)) else []
                        search_cells += cells
                        for c in search_cells:
                            m = re.search(r"[A-Z][a-z]{2}-\d{2}", c)
                            if m: month = m.group(); break
                            m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", c)
                            if m:
                                day, mo, yr = m.groups()
                                mon_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                                try:
                                    month = mon_names[int(mo)-1] + "-" + yr[-2:]
                                    break
                                except (ValueError, IndexError):
                                    pass
                        # 抽 dividend
                        div_val = None
                        if div_col >= 0 and div_col < len(cells):
                            m = re.search(r"\d+\.\d+", cells[div_col])
                            if m: div_val = float(m.group())
                        # 抽 yield (年度化優先)
                        yld_val = None
                        if yld_col >= 0 and yld_col < len(cells):
                            m = re.search(r"\d+\.\d+", cells[yld_col])
                            if m: yld_val = float(m.group())
                        if month and div_val is not None and yld_val is not None:
                            return {"month": month, "dividendPerShare": div_val, "yieldPct": yld_val}
        # === Strategy 2: text-line regex (line-by-line, 揀最後一個 % 做 annualized yield) ===
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = ""
            for p in pdf.pages:
                t = p.extract_text()
                if t:
                    text += t + "\n"
        mon_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 月份偵測 — Mon-YY 或 DD/MM/YYYY
            month = ""
            mm = re.search(r"\b([A-Z][a-z]{2})-(\d{2})\b", line)
            if mm:
                month = mm.group(1) + "-" + mm.group(2)
            else:
                mm = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", line)
                if mm:
                    try:
                        month = mon_names[int(mm.group(2))-1] + "-" + mm.group(3)[-2:]
                    except (ValueError, IndexError):
                        pass
            if not month:
                continue
            # 揀第一個 0.xxxx 做 dividend, 揀最後一個 NN.NN(%) 做 annualized yield
            div_match = re.search(r"(?<![\d.])(0\.\d{3,7})(?![\d.])", line)
            yld_matches = re.findall(r"\b(\d{1,2}\.\d{1,2})\s*%?", line)
            if not div_match or not yld_matches:
                continue
            div_val = float(div_match.group(1))
            # 篩走 0.xx% (單期 yield 通常 < 2%)、保留 > 2% 嘅
            big_ylds = [float(y) for y in yld_matches if float(y) >= 2.0]
            yld_val = big_ylds[-1] if big_ylds else float(yld_matches[-1])
            return {"month": month, "dividendPerShare": div_val, "yieldPct": yld_val}

        # === Strategy 3: whole-text window (處理 cell 拆 line 嘅 PDF, eg Allianz 中文版) ===
        # 揀第一個日期 occurrence, 喺之後 500 字內搵 dividend + yield
        first_date = None
        for m in re.finditer(r"\b([A-Z][a-z]{2})-(\d{2})\b|\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
            if m.group(1):
                first_date = (m.group(1) + "-" + m.group(2), m.end())
            else:
                try:
                    mn = mon_names[int(m.group(4))-1] + "-" + m.group(5)[-2:]
                    first_date = (mn, m.end())
                except (ValueError, IndexError):
                    continue
            break
        if first_date:
            month, pos = first_date
            window = text[pos:pos+500]
            div_m = re.search(r"(?<![\d.])(0\.\d{3,7})(?![\d.])", window)
            # 攞所有百分比 candidates, 揀最後一個 >= 2% (年度化通常 5-15%)
            pct_candidates = re.findall(r"(\d{1,2}\.\d{1,2})\s*%", window)
            if not pct_candidates:
                # 無 % sign 嘅 fallback
                pct_candidates = re.findall(r"\b(\d{1,2}\.\d{2})\b", window)
            big = [float(y) for y in pct_candidates if 2.0 <= float(y) <= 25.0]
            if div_m and big:
                return {"month": month, "dividendPerShare": float(div_m.group(1)), "yieldPct": big[-1]}
            # === Strategy 3b: 有 dividend 但冇 yield (eg Allianz「派息成分」PDF) ===
            # 返回 dividend, yieldPct = None, 由 caller 用 newPrice 自己算
            if div_m:
                return {"month": month, "dividendPerShare": float(div_m.group(1)), "yieldPct": None}
        # === Debug dump: save extracted text for failed funds ===
        try:
            debug_dir = REPO_ROOT / "scripts" / "_debug_dividends"
            debug_dir.mkdir(exist_ok=True)
            (debug_dir / f"{code}.txt").write_text(
                f"=== PDF text extracted for {code} ===\n\n{text[:3000]}\n",
                encoding="utf-8"
            )
        except Exception:
            pass
        return None
    except Exception as e:
        print(f"    ⚠️  {code} dividend fetch error: {e}")
        return None


def fetch_all_dividends(codes: set) -> dict:
    """逐隻基金 fetch 派息 PDF (sequential 避免 hammer AIA server)"""
    if not PDF_OK:
        return {}
    print(f"\n[{hk_now()}] 開始抓 {len(codes)} 隻基金派息 PDF...")
    result = {}
    for code in sorted(codes):
        div = fetch_dividend(code)
        if div:
            result[code] = div
            print(f"  ✓ {code}: {div['month']} 派息 ${div['dividendPerShare']:.6f} (年息 {div['yieldPct']:.2f}%)")
        else:
            print(f"  ○ {code}: 冇派息 PDF / parse 失敗")
    print(f"\n  📊 派息抓取: {len(result)}/{len(codes)} 隻成功")
    return result


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

    # === 抓派息 PDF + 更新真實派息率 ===
    dividends = fetch_all_dividends(expected)
    div_updated = []
    for code, div in dividends.items():
        if code not in config["funds"]:
            continue
        f = config["funds"][code]
        old_yield = f.get("latestYieldPct")
        f["latestDividendPerShare"] = div["dividendPerShare"]
        f["dividendMonth"] = div["month"]
        # yieldPct: PDF 有就用官方值, 冇就用 div×12/price 估算 (eg Allianz「派息成分」PDF)
        if div.get("yieldPct") is not None:
            f["latestYieldPct"] = div["yieldPct"]
            f["yieldEstimated"] = False
        else:
            price = f.get("newPrice", 0)
            if price > 0:
                f["latestYieldPct"] = round(div["dividendPerShare"] * 12 / price * 100, 2)
                f["yieldEstimated"] = True
            else:
                continue
        f["annYield"] = round(f["latestYieldPct"] / 100, 4)
        f["_lastDividendUpdate"] = hk_now()
        if old_yield != f["latestYieldPct"]:
            mark = " (估算)" if f.get("yieldEstimated") else ""
            div_updated.append(f"{code}: {old_yield}% → {f['latestYieldPct']}%{mark} ({div['month']})")

    # === Phase 1: Allianz 月報攞官方 yield (取代估算) ===
    try:
        factsheet_urls = scrape_factsheet_urls(ALLIANZ_FUNDS)
        for code, fs_url in factsheet_urls.items():
            if code not in config["funds"]:
                continue
            print(f"  📄 解析 {code} 月報...")
            fs_data = fetch_factsheet_dividend(code, fs_url)
            if fs_data and fs_data.get("yieldPct"):
                f = config["funds"][code]
                old = f.get("latestYieldPct")
                f["latestYieldPct"] = fs_data["yieldPct"]
                f["latestDividendPerShare"] = fs_data["dividendPerShare"]
                f["dividendMonth"] = fs_data["month"]
                f["annYield"] = round(fs_data["yieldPct"] / 100, 4)
                f["yieldEstimated"] = False
                f["_lastDividendUpdate"] = hk_now()
                div_updated.append(f"{code}: {old}% → {fs_data['yieldPct']}% (官方月報 {fs_data['month']})")
                print(f"  ✓ {code}: {fs_data['yieldPct']}% (官方)")
            else:
                print(f"  ✗ {code}: 月報 parse 失敗")
    except Exception as e:
        print(f"⚠️  月報抓取失敗 (繼續): {e}")

    config["lastUpdated"] = hk_now()
    if scraped.get("lastPriceDate"):
        config["lastPriceDate"] = scraped["lastPriceDate"]

    with open(FUNDS_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}\n  ✅ 完成總結\n{'='*60}")
    print(f"✓ 價格更新: {len(updated)} 隻")
    for u in updated: print(f"   {u}")
    print(f"○ 價格無變化: {len(skipped)} 隻")
    print(f"💰 派息率更新: {len(div_updated)} 隻")
    for d in div_updated: print(f"   {d}")
    print(f"📅 評估日: {config.get('lastPriceDate', 'N/A')}")
    print(f"🕐 更新時間: {config['lastUpdated']}\n")


if __name__ == "__main__":
    main()
