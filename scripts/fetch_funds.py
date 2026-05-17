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
from urllib.parse import urljoin

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
            # 接受 prefix: Z (派息) + H/CG/I/P/W/D (增長型) — 即係 expected_codes 包含嘅都收
            if not code or code not in expected_codes:
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

# === 增長型基金 (非派息) — 由 detail 頁 chart 攞歷史回報 ===
GROWTH_FUNDS = {"H01", "CG1", "I07", "I09", "P04", "W04", "D14"}
DETAIL_URL_FMT = "https://www.aia.com.hk/zh-hk/help-and-support/individuals/investment-information/investment-options-prices/details.html?id={code}&cat=TMP2&lang=zh"


def scrape_growth_returns(codes: set) -> dict:
    """Navigate detail page → extract chart price history → compute 1/3/5 yr returns"""
    if not codes:
        return {}
    print(f"\n[{hk_now()}] 抓增長型基金歷史回報: {sorted(codes)}")
    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-HK",
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        captured = {}
        # 捕獲所有 XHR JSON response (chart data 通常用 XHR)
        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct.lower() or resp.url.endswith(".json"):
                    body = resp.body()
                    if body and 100 < len(body) < 2_000_000:
                        captured[resp.url] = body.decode("utf-8", errors="ignore")
            except Exception:
                pass
        page.on("response", on_response)

        all_xhr_urls = []
        def on_response_log(resp):
            try:
                if resp.request.resource_type in ("xhr", "fetch"):
                    all_xhr_urls.append((resp.url, resp.status, resp.headers.get("content-type", "")))
            except Exception:
                pass
        page.on("response", on_response_log)

        for code in sorted(codes):
            url = DETAIL_URL_FMT.format(code=code)
            try:
                captured.clear()
                all_xhr_urls.clear()
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(5000)
                # Debug: dump first fund's XHR list
                if code == sorted(codes)[0]:
                    try:
                        debug_dir = REPO_ROOT / "scripts" / "_debug_dividends"
                        debug_dir.mkdir(exist_ok=True)
                        lines = [f"=== {code} XHR captured ({len(all_xhr_urls)}) ==="]
                        for u, st, ct in all_xhr_urls:
                            lines.append(f"[{st}] {ct[:40]} | {u}")
                        # 同時 dump 任何 JSON body 嘅前 800 chars
                        lines.append("\n=== JSON bodies (first 800 chars each) ===")
                        for u, b in list(captured.items())[:5]:
                            lines.append(f"\n--- {u} ---\n{b[:800]}")
                        (debug_dir / f"{code}_detail_xhr.txt").write_text("\n".join(lines), encoding="utf-8")
                    except Exception:
                        pass
                # 嘗試㩒「All」按鈕令全部歷史數據 load 落 chart (各種 selector + JS click 都試)
                clicked = False
                for label in ["All", "全部", "5Y", "5年"]:
                    if clicked: break
                    for sel in [f"button:has-text('{label}')", f"a:has-text('{label}')", f"*[role='button']:has-text('{label}')"]:
                        try:
                            els = page.locator(sel).all()
                            for el in els:
                                if el.is_visible(timeout=1000):
                                    el.click(timeout=3000, force=True)
                                    clicked = True
                                    break
                            if clicked: break
                        except Exception:
                            continue
                # JS fallback: 揾所有 button/a 文字內容並 click
                if not clicked:
                    try:
                        clicked = page.evaluate("""
                            () => {
                                for (const el of document.querySelectorAll('button, a, [role="button"]')) {
                                    const t = (el.textContent || '').trim();
                                    if (t === 'All' || t === '全部' || t === '5Y') {
                                        el.click();
                                        return true;
                                    }
                                }
                                return false;
                            }
                        """)
                    except Exception:
                        pass
                # 等 chart reload — XHR + render
                page.wait_for_timeout(6000)
                # Method 1: JS evaluate to find chart instance
                series = page.evaluate("""
                    () => {
                        const tryArrays = [];
                        // Highcharts
                        if (window.Highcharts && Highcharts.charts) {
                            for (const c of Highcharts.charts) {
                                if (!c || !c.series) continue;
                                for (const s of c.series) {
                                    if (!s || !s.data || s.data.length < 10) continue;
                                    tryArrays.push(s.data.map(p => {
                                        if (p && p.x !== undefined) return [p.x, p.y];
                                        if (Array.isArray(p) && p.length >= 2) return [p[0], p[1]];
                                        return null;
                                    }).filter(Boolean));
                                }
                            }
                        }
                        // ECharts
                        if (window.echarts && document.querySelectorAll) {
                            for (const el of document.querySelectorAll('[_echarts_instance_]')) {
                                try {
                                    const inst = echarts.getInstanceByDom(el);
                                    const opt = inst && inst.getOption();
                                    if (opt && opt.series) {
                                        for (const s of opt.series) {
                                            if (s.data && s.data.length > 10) {
                                                tryArrays.push(s.data.map(p => Array.isArray(p) ? [p[0], p[1]] : [null, p]).filter(p => p[0]));
                                            }
                                        }
                                    }
                                } catch(e){}
                            }
                        }
                        // Pick longest array
                        if (tryArrays.length === 0) return null;
                        tryArrays.sort((a,b) => b.length - a.length);
                        return tryArrays[0];
                    }
                """)
                # Method 2 fallback: parse captured XHR JSON for date/price arrays
                if not series:
                    for url_c, body in captured.items():
                        try:
                            import json as _json
                            data = _json.loads(body)
                            # Try common shapes
                            candidates = []
                            def walk(obj, depth=0):
                                if depth > 5: return
                                if isinstance(obj, list) and len(obj) > 30:
                                    if all(isinstance(x, (list, dict)) for x in obj[:5]):
                                        candidates.append(obj)
                                elif isinstance(obj, dict):
                                    for v in obj.values():
                                        walk(v, depth+1)
                            walk(data)
                            if candidates:
                                candidates.sort(key=len, reverse=True)
                                best = candidates[0]
                                normalized = []
                                for item in best:
                                    if isinstance(item, list) and len(item) >= 2:
                                        normalized.append([item[0], item[1]])
                                    elif isinstance(item, dict):
                                        ts = item.get("x") or item.get("date") or item.get("t")
                                        v = item.get("y") or item.get("price") or item.get("v") or item.get("value")
                                        if ts and v: normalized.append([ts, v])
                                if len(normalized) > 30:
                                    series = normalized
                                    break
                        except Exception:
                            continue
                if not series or len(series) < 30:
                    print(f"  ✗ {code}: chart data 攞唔到 (captured {len(captured)} XHR)")
                    continue
                # Normalize: timestamp might be ms or seconds
                pts = []
                for p in series:
                    try:
                        ts = float(p[0]); price = float(p[1])
                        if ts > 1e12:  # already ms
                            pass
                        elif ts > 1e9:  # seconds → ms
                            ts *= 1000
                        else:
                            continue  # weird value
                        pts.append((ts, price))
                    except Exception:
                        continue
                if len(pts) < 30:
                    print(f"  ✗ {code}: normalized 太少 ({len(pts)})")
                    continue
                pts.sort()
                today_ts = pts[-1][0]
                today_price = pts[-1][1]
                def pct_change(years_ago):
                    target = today_ts - years_ago * 365.25 * 86400 * 1000
                    for ts, pr in reversed(pts):
                        if ts <= target and pr > 0:
                            return round((today_price - pr) / pr * 100, 2)
                    return None
                rs = {"r1": pct_change(1), "r3": pct_change(3), "r5": pct_change(5)}
                # Time span check
                span_days = (today_ts - pts[0][0]) / 86400000
                result[code] = rs
                hint = "" if span_days >= 365 * 5 else f" ⚠️ 只有 {span_days:.0f} 日數據, click 'All' 可能 fail"
                print(f"  ✓ {code}: 1Y={rs['r1']} 3Y={rs['r3']} 5Y={rs['r5']} (源: {len(pts)} 個 data points, ~{span_days:.0f} 日){hint}")
            except Exception as e:
                print(f"  ✗ {code}: {e}")
        browser.close()
    print(f"  📊 歷史回報抓取: {len(result)}/{len(codes)} 隻成功")
    return result


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
            # === Pass 1: 一次過攞晒所有 detail URLs (因為 navigate 後 row reference 會 stale) ===
            detail_urls = {}
            rows = page.locator("tr").all()
            for row in rows:
                try:
                    cells = row.locator("td").all()
                    if len(cells) < 2:
                        continue
                    code = cells[1].inner_text().strip()
                    if code not in codes:
                        continue
                    for link in row.locator("a").all():
                        href = link.get_attribute("href")
                        if href and "details.html" in href:
                            detail_urls[code] = urljoin(AIA_URL, href)
                            break
                except Exception:
                    continue
            print(f"  📋 Detail URLs 取得: {len(detail_urls)}/{len(codes)} - {sorted(detail_urls.keys())}")
            # === Pass 2: 逐個 navigate 攞基金月報 URL ===
            for code in sorted(codes):
                detail_href = detail_urls.get(code)
                if not detail_href:
                    print(f"  ✗ {code}: 喺 prices 表搵唔到 detail link")
                    continue
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
                        href = urljoin(page.url, href)
                        result[code] = href
                        print(f"  ✓ {code}: {href.split('/')[-1]}")
                    else:
                        print(f"  ✗ {code}: detail 頁冇基金月報 link")
                except Exception as e:
                    print(f"  ✗ {code}: navigate fail - {e}")
        finally:
            browser.close()
    return result


def parse_allianz_factsheet(pdf_bytes: bytes, code: str = "") -> dict | None:
    """Allianz 月報 parser: 揾「年度化股息收益率」第一個 data row
    PDF table 結構: 紀錄日 | 除息日 | 每股派息 | 除息日資產淨值 | 股息收益率 | 年度化股息收益率
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = ""
            for p in pdf.pages:
                t = p.extract_text()
                if t: text += t + "\n"
        mon_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        # Strategy A: 行內含 2 個 dates + 2+ percentages
        for line in text.split("\n"):
            line = line.strip()
            if not line: continue
            dates = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", line)
            if len(dates) < 2: continue
            pcts = re.findall(r"(\d{1,2}\.\d{1,2})\s*%", line)
            if len(pcts) < 2: continue
            annualized = float(pcts[-1])
            divs = re.findall(r"(?<![\d.])(0\.\d{3,7})(?![\d.])", line)
            if not divs: continue
            d, m, y = dates[0].split("/")
            try:
                month = mon_names[int(m)-1] + "-" + y[-2:]
            except (ValueError, IndexError):
                continue
            return {"month": month, "dividendPerShare": float(divs[0]), "yieldPct": annualized}
        # Strategy B: cells 拆 line — 揾第一個 date 之後 window 內嘅 numbers
        first_date_pos = None
        first_date_str = None
        for mm in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
            try:
                first_date_str = mon_names[int(mm.group(2))-1] + "-" + mm.group(3)[-2:]
                first_date_pos = mm.end()
                break
            except (ValueError, IndexError):
                continue
        if first_date_pos:
            window = text[first_date_pos:first_date_pos+400]
            divs = re.findall(r"(?<![\d.])(0\.\d{3,7})(?![\d.])", window)
            pcts = re.findall(r"(\d{1,2}\.\d{1,2})\s*%", window)
            big_pcts = [float(p) for p in pcts if 1.0 <= float(p) <= 25.0]
            if divs and big_pcts:
                return {"month": first_date_str, "dividendPerShare": float(divs[0]), "yieldPct": big_pcts[-1]}
        # === Debug dump for parser failure ===
        if code:
            try:
                debug_dir = REPO_ROOT / "scripts" / "_debug_dividends"
                debug_dir.mkdir(exist_ok=True)
                (debug_dir / f"{code}_allianz_factsheet.txt").write_text(
                    f"=== Allianz factsheet text for {code} ===\n\n{text[:5000]}\n",
                    encoding="utf-8"
                )
            except Exception:
                pass
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
            return parse_allianz_factsheet(r.content, code)
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
                        # Sanity: 年度化 yield 通常 > 1%, 太細就唔 trust
                        if yld_val is not None and yld_val < 1.0:
                            yld_val = None
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
            # 揀最後一個 >= 1% 嘅 % 做 annualized yield, 冇就視為冇 yield (let caller estimate)
            big_ylds = [float(y) for y in yld_matches if float(y) >= 1.0]
            yld_val = big_ylds[-1] if big_ylds else None
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
            yld_str = f"{div['yieldPct']:.2f}%" if div.get('yieldPct') is not None else "估算"
            print(f"  ✓ {code}: {div['month']} 派息 ${div['dividendPerShare']:.6f} (年息 {yld_str})")
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
        # === Manual override 保護: 有 manualYieldPct 就用佢, 唔覆蓋 ===
        if f.get("manualYieldPct") is not None:
            f["latestYieldPct"] = f["manualYieldPct"]
            f["yieldEstimated"] = False
        elif div.get("yieldPct") is not None:
            f["latestYieldPct"] = div["yieldPct"]
            f["yieldEstimated"] = False
        else:
            # 冇 PDF yield + 冇 manual → 用 div×12/price 估算
            price = f.get("newPrice", 0)
            if price > 0:
                f["latestYieldPct"] = round(div["dividendPerShare"] * 12 / price * 100, 2)
                f["yieldEstimated"] = True
            else:
                continue
        f["annYield"] = round(f["latestYieldPct"] / 100, 4)
        f["_lastDividendUpdate"] = hk_now()
        if old_yield != f["latestYieldPct"]:
            mark = " (手動)" if f.get("manualYieldPct") else (" (估算)" if f.get("yieldEstimated") else "")
            div_updated.append(f"{code}: {old_yield}% → {f['latestYieldPct']}%{mark} ({div['month']})")

    # Phase 1 (Allianz factsheet scraping) 已棄用 — PDF 用 image font, pdfplumber 抽唔到
    # 改用 manualYieldPct 人手 override (見 funds.json Z07 / Z08)

    # 增長型基金歷史回報 (Playwright chart scraping) 已棄用 — AIA chart 預設只 load 6 個月,
    # click "All" 觸發唔到 Angular SPA, 改用 _returnsSource 人手 update funds.json (見 H01 等)

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
