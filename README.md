# 卓達智悅基金分析工具 (PWA)

互動式分析工具,支援 24 隻 AIA USD Z 字頭基金 + 6 個預設組合 + 自選組合 + HKD/RMB 雙幣顯示。

## ✨ 自動化功能 🤖

**每星期日凌晨 2:00 (香港時間),GitHub Actions 自動:**
1. 開 Headless Chrome 訪問 AIA 投資選擇頁
2. 抓取所有 24 隻 USD Z 字頭基金最新價格
3. 更新 `data/funds.json`
4. 自動 commit & push (有變化先會 commit)
5. iPhone 主畫面個 App 下次開,自動讀到最新價

**手動觸發:** 入 GitHub repo → Actions → "自動更新基金價格" → Run workflow

## 📁 檔案結構

```
github_deploy/
├── index.html              ← 主工具 (PWA-ready, 從 funds.json 讀數據)
├── manifest.json           ← PWA 設定
├── data/
│   └── funds.json          ← 基金資料 (價格自動更新, 其他 metadata 手動)
├── scripts/
│   └── fetch_funds.py      ← Playwright 爬蟲腳本
├── .github/workflows/
│   └── update-funds.yml    ← GitHub Actions 排程 (每星期日凌晨)
├── apple-touch-icon.png    ← iPhone 主畫面圖示 (180x180)
├── icon-192.png            ← Android PWA 圖示
├── icon-512.png            ← PWA 啟動畫面
├── favicon-32.png          ← 瀏覽器分頁
└── .nojekyll               ← GitHub Pages 必備
```

## 📦 部署到 GitHub Pages (一次性)

### 1. 上傳所有檔案 (包括子目錄)
```powershell
cd "D:\ClaudeAI\AIA Fund Analyzer\github_deploy"
git add .
git commit -m "Add auto-update workflow + funds.json data"
git push -u origin main --force
```

### 2. 啟用 GitHub Pages
1. Repo → Settings → Pages
2. Source: `Deploy from a branch` → Branch: `main` → Folder: `/ (root)` → Save
3. 等 1-2 分鐘,網址 `https://millkei427.github.io/aia-fund-tool/` 生效

### 3. 啟用 GitHub Actions
1. Repo → Actions tab
2. 如果見到 "Workflows aren't being run on this forked repository" 點 "I understand my workflows, go ahead and enable them"
3. 揀「自動更新基金價格」 → Run workflow (測試一次)
4. 等 2-3 分鐘,Actions 頁顯示 ✅ 即成功

之後每星期日凌晨 2:00 自動跑,完全唔需要你管。

## 📱 加到 iPhone 主畫面

1. **Safari** 打開 `https://millkei427.github.io/aia-fund-tool/`
2. 點底部 **分享 ↗** → **加入主畫面**
3. 改名「AIA 基金」 → 加入

## 🛠️ 主要功能

- 7 個 tabs: 集中型 / 分散型 / 北美 / 亞洲 / 科技 / 消費 / 自選
- 24 隻 USD Z 字頭基金可任意組合
- HKD ↔ 人民幣即時雙幣顯示
- 多年累積派息模擬 (1/3/5/10/20/30 年)
- 1年 / 3年 / 5年歷史回報數據
- 累積派息趨勢圖 + 地區分佈圓環圖
- **🤖 每星期自動更新基金價格**

## 🔄 手動更新基金 metadata

`data/funds.json` 入面以下欄位係手動維護 (因為 AIA 一個季度先更新一次):
- `annYield` (年度化派息率)
- `r1`, `r3`, `r5` (1年/3年/5年累積回報)
- `risk` (風險類別)
- `regionGroup` (地區分組)
- `cls` (資產類別)

當你收到新嘅 AIA「可派息投資選擇」文件,直接編輯 `funds.json` 嘅相應欄位即可。Push 上去,iPhone App 立刻反映。

## 📚 AIA 官方參考

- [投資選擇資訊](https://www.aia.com.hk/zh-hk/help-and-support/individuals/investment-information/investment-options-prices.html)
- [投資年期與回報](https://www.aia.com.hk/zh-hk/help-and-support/individuals/investment-information/education-module/time-horizon.html)
- [平均成本法](https://www.aia.com.hk/zh-hk/help-and-support/individuals/investment-information/education-module/dollar-cost-averaging.html)

數據來源:AIA 官方公佈
基金價格自動更新 (每星期日凌晨)
其他 metadata 手動更新 (一個季度一次)
