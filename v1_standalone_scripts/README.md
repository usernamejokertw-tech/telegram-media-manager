# V1: Standalone Scripts (獨立執行版)

這是專案的早期版本，採用「功能分離」的設計哲學。
掃描器 (`scanner.py`) 與 播放器 (`bot.py`) 是兩個獨立運作的程式，適合需要長時間背景掃描，但不想一直開著 Bot 介面的情境。

## 📂 檔案結構

- `scanner.py`: **[資料維護端]** \* 負責增量掃描 (`/index`) 與資料庫維護 (`/scan`)。
  - 通常在需要更新影片庫時才執行。
- `bot.py`: **[使用者介面端]**
  - 提供 Telegram Bot 按鈕介面。
  - 負責讀取 JSON 資料庫並執行隨機播放、收藏與刪除。

## 🚀 如何使用

### 1. 準備工作

確保此資料夾內有以下設定檔（可從上層目錄複製）：

- `config.py`: 包含 API ID, HASH, TOKEN。
- `tag.json`: 標籤分類設定。

### 2. 執行掃描器 (Scanner)

當你需要更新資料庫時：

```bash
python scanner.py

在任何群組輸入 /index：進行增量更新（只抓新影片）。

在任何群組輸入 /scan：進行全量維護（改名與清理失效檔）。

3. 執行播放器 (Bot)
當你想看影片時：

Bash
python bot.py
私訊你的 Bot 輸入 /start 即可叫出控制面板。
```
