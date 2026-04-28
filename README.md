# 卓達智悅基金分析工具 (PWA)

互動式分析工具,支援 24 隻 AIA USD Z 字頭基金 + 6 個預設組合 + 自選組合 + HKD/RMB 雙幣顯示。

## 📦 部署到 GitHub Pages

### 步驟 1: 建立 GitHub Repository

1. 登入 GitHub,點擊 `New repository`
2. Repository name: 例如 `aia-fund-tool` (任意名稱)
3. **Public** (GitHub Pages 免費版要 Public)
4. 唔需要剔 README/gitignore/license
5. 點擊 `Create repository`

### 步驟 2: 上傳檔案

最簡單方法 - **拖拉上傳**:

1. 喺新 repo 頁面點擊 **"uploading an existing file"** 連結
2. 將呢個 `github_deploy` folder 入面**所有檔案**拖入瀏覽器:
   - `index.html`
   - `manifest.json`
   - `apple-touch-icon.png`
   - `icon-192.png`
   - `icon-512.png`
   - `favicon-32.png`
   - `.nojekyll` (注意呢個係隱藏檔案,Mac 要按 Cmd+Shift+. 顯示)
3. Commit message 隨便填,點 `Commit changes`

### 步驟 3: 啟用 GitHub Pages

1. 入 repo 嘅 `Settings` → 左欄揀 `Pages`
2. **Source**: 揀 `Deploy from a branch`
3. **Branch**: 揀 `main` (或 `master`),folder 揀 `/ (root)`
4. 點 `Save`
5. 等 1-2 分鐘,頁面頂部會顯示你個網址,例如:
   ```
   https://你的username.github.io/aia-fund-tool/
   ```

## 📱 加到 iPhone 主畫面 (Add to Home Screen)

1. 用 **Safari** (唔可以用 Chrome) 打開你嘅 GitHub Pages 網址
2. 點底部嘅 **分享按鈕** (方形向上箭頭 ↗)
3. 向下捲動,點 **「加入主畫面」 (Add to Home Screen)**
4. 改個名字 (例如「AIA 基金」),點 **加入**
5. 主畫面就會出現一個紅色 AIA 圖示,點開就好似真 App 一樣全螢幕顯示

### 💡 使用貼士

- **第一次打開要有網絡** (要載入 Chart.js 圖表庫),之後可以離線部份功能
- 想完全離線? 我可以再加 Service Worker 進階功能 (話我知)
- 工具會自動保存喺主畫面,唔會佔記憶體,係即點即用嘅 web app
- 點到外面連結 (例如 AIA 官網) 會自動跳轉返 Safari

## 🔄 更新工具

當有新版本嘅時候:
1. 喺 GitHub repo 上傳新嘅 `index.html` (覆蓋舊嘅)
2. iPhone 主畫面個 App 會自動讀到最新版本 (清理 Safari cache 即時生效)

## 📋 檔案清單

| 檔案 | 用途 |
|---|---|
| `index.html` | 主工具 (含 PWA meta tags) |
| `manifest.json` | PWA 設定 (App 名稱、顏色、圖示) |
| `apple-touch-icon.png` | iPhone 主畫面圖示 (180x180) |
| `icon-192.png` | Android Chrome PWA 圖示 |
| `icon-512.png` | PWA 啟動畫面圖示 |
| `favicon-32.png` | 瀏覽器分頁小圖示 |
| `.nojekyll` | 確保 GitHub Pages 唔會 process 個 site |

## 🛠️ 主要功能

- 7 個 tabs: 組合 A 集中型 / 組合 B 分散型 / 北美市場 / 亞洲市場 / 科技類 / 消費類 / 自選組合
- 24 隻 USD Z 字頭基金可任意組合, 自定比例
- HKD ↔ 人民幣即時雙幣顯示
- 多年累積派息模擬 (1/3/5/10/20/30 年, 含複利選項)
- 1年 / 3年 / 5年歷史回報數據
- 累積派息趨勢圖 + 地區分佈圓環圖

數據來源:AIA 官方公佈 (基金價格 04/24/2026,歷史回報截至 2026/03/31)
