# ============================================================
# AIA Fund Tool - GitHub 自動部署 Script
# ============================================================
# 使用方法:
#   1. 喺 PowerShell 入面 cd 到呢個 folder
#   2. 執行: .\deploy.ps1
#
# 第一次 push 會彈出 GitHub 登入視窗 (Git Credential Manager)
# 用瀏覽器登入後, 之後 push 就唔需要再登入
# ============================================================

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/millkei427/aia-fund-tool.git"
$PagesUrl = "https://millkei427.github.io/aia-fund-tool/"

# 切換到 script 所在嘅 folder
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " 🚀 AIA Fund Tool - GitHub 部署" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📂 工作目錄: $PSScriptRoot" -ForegroundColor Gray
Write-Host "🔗 目標 Repo: $RepoUrl" -ForegroundColor Gray
Write-Host ""

# ---- Step 1: 檢查 git ----
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 找不到 git!" -ForegroundColor Red
    Write-Host "   請先安裝 Git for Windows: https://git-scm.com/download/win" -ForegroundColor Yellow
    Read-Host "按 Enter 結束"
    exit 1
}

# ---- Step 2: 設定 git user (如果未設定) ----
$gitUser = git config user.name 2>$null
$gitEmail = git config user.email 2>$null
if (-not $gitUser) {
    Write-Host "⚙️  設定 git user.name = millkei427" -ForegroundColor Yellow
    git config --global user.name "millkei427"
}
if (-not $gitEmail) {
    Write-Host "⚙️  設定 git user.email = millkei427@gmail.com" -ForegroundColor Yellow
    git config --global user.email "millkei427@gmail.com"
}

# ---- Step 3: 初始化 git repo (如果未初始化) ----
if (-not (Test-Path ".git")) {
    Write-Host "🔧 初始化新嘅 git repository..." -ForegroundColor Yellow
    git init | Out-Null
    git branch -M main
} else {
    Write-Host "✓ Git repo 已存在" -ForegroundColor Green
}

# ---- Step 4: 設定 / 更新 remote ----
$existingRemote = git remote get-url origin 2>$null
if (-not $existingRemote) {
    Write-Host "🔗 加入 remote origin..." -ForegroundColor Yellow
    git remote add origin $RepoUrl
} elseif ($existingRemote -ne $RepoUrl) {
    Write-Host "🔄 更新 remote URL..." -ForegroundColor Yellow
    git remote set-url origin $RepoUrl
} else {
    Write-Host "✓ Remote URL 已正確設定" -ForegroundColor Green
}

# ---- Step 5: Add + Commit ----
Write-Host ""
Write-Host "➕ 加入所有檔案..." -ForegroundColor Yellow
git add .

# 檢查有冇變更
$hasChanges = git status --porcelain
if (-not $hasChanges) {
    Write-Host "ℹ️  冇任何變更需要 commit" -ForegroundColor Cyan
} else {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
    $commitMsg = "Deploy AIA Fund Tool - $timestamp"
    Write-Host "💾 Commit: $commitMsg" -ForegroundColor Yellow
    git commit -m $commitMsg | Out-Null
    Write-Host "✓ Commit 完成" -ForegroundColor Green
}

# ---- Step 6: Push ----
Write-Host ""
Write-Host "🚀 Push 到 GitHub..." -ForegroundColor Yellow
Write-Host "   (第一次會彈出登入視窗, 用瀏覽器登入即可)" -ForegroundColor Gray
Write-Host ""

# 嘗試正常 push
$pushOk = $false
try {
    git push -u origin main 2>&1 | Tee-Object -Variable pushOutput
    if ($LASTEXITCODE -eq 0) {
        $pushOk = $true
    }
} catch {
    $pushOk = $false
}

# 如果 push 失敗 (例如 repo 已有 README), 嘗試合併後再 push
if (-not $pushOk) {
    Write-Host ""
    Write-Host "⚠️  Push 失敗。嘗試合併 remote 後再 push..." -ForegroundColor Yellow
    try {
        git pull origin main --rebase --allow-unrelated-histories 2>&1 | Out-Null
        git push -u origin main 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pushOk = $true
        }
    } catch {
        Write-Host ""
        Write-Host "❌ 仍然失敗。如果 repo 已有衝突檔案, 可以強制覆蓋:" -ForegroundColor Red
        Write-Host "   git push -u origin main --force" -ForegroundColor White
        Write-Host ""
        $forceConfirm = Read-Host "係咪要強制覆蓋 remote? (y/N)"
        if ($forceConfirm -eq "y" -or $forceConfirm -eq "Y") {
            git push -u origin main --force
            if ($LASTEXITCODE -eq 0) {
                $pushOk = $true
            }
        }
    }
}

# ---- Step 7: 結果 ----
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
if ($pushOk) {
    Write-Host " ✅ 部署成功!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "📋 下一步: 啟用 GitHub Pages" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  1. 開啟以下網址 (即將打開):" -ForegroundColor White
    Write-Host "     https://github.com/millkei427/aia-fund-tool/settings/pages" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  2. Source 揀: Deploy from a branch" -ForegroundColor White
    Write-Host "  3. Branch  揀: main  →  Folder: / (root)" -ForegroundColor White
    Write-Host "  4. 點 Save, 等 1-2 分鐘" -ForegroundColor White
    Write-Host ""
    Write-Host "  5. 完成後喺 iPhone Safari 打開:" -ForegroundColor White
    Write-Host "     $PagesUrl" -ForegroundColor Cyan
    Write-Host "     再點 [分享] → [加入主畫面]" -ForegroundColor White
    Write-Host ""

    # 自動打開 GitHub Pages 設定頁
    $openSettings = Read-Host "係咪要而家自動打開 GitHub Pages 設定頁? (Y/n)"
    if ($openSettings -ne "n" -and $openSettings -ne "N") {
        Start-Process "https://github.com/millkei427/aia-fund-tool/settings/pages"
    }
} else {
    Write-Host " ❌ 部署未完成" -ForegroundColor Red
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "可能原因:" -ForegroundColor Yellow
    Write-Host "  • GitHub 登入視窗冇成功登入" -ForegroundColor White
    Write-Host "  • Repo 唔存在 (請先去 GitHub 建立)" -ForegroundColor White
    Write-Host "  • 網絡問題" -ForegroundColor White
    Write-Host ""
    Write-Host "可以手動執行:" -ForegroundColor Yellow
    Write-Host "  git push -u origin main --force" -ForegroundColor White
}

Write-Host ""
Read-Host "按 Enter 結束"
