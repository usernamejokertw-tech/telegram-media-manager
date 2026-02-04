# Telegram Media Manager Assistant (TG 影音整合助理)

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Library](https://img.shields.io/badge/Library-Telethon-orange)

## 📖 專案介紹 (Introduction)

Telegram 提供近乎無限大的雲端儲存空間，我個人習慣用它來儲存各種學習資源，並透過 Group 和 Topic 進行分類。
但隨著時間推移，群組內的內容多到我根本沒有機會去翻閱那些久遠以前儲存的資源。

**「存了不看，等於沒存。」**

所以我想寫一個能**隨機播放**我所擁有資源的系統，強迫自己去複習。寫著寫著，又覺得應該要有收藏功能、更精細的標籤分類，甚至是一鍵自動更新...
最後決定把所有功能整合在一起，讓機器人來處理這些雜事。

## ⚙️ 運作原理 (How it works)

本系統採用 **雙核心架構 (UserBot + Bot)**：

* **User Client (使用者分身)**：
    * 因為我的群組大部分是**私人 (Private)** 的，一般的 Bot 無法讀取歷史訊息或下載檔案。
    * 所以抓取資料、轉傳檔案、解析連結這些需要高權限的行為，都是由 User Client 代替我本人執行的。
* **Bot Client (介面互動)**：
    * 負責提供漂亮的按鈕介面、選單、處理指令，讓操作更直覺。

## ✨ 功能特色

* **🎲 隨機播放**：從你的資源庫中隨機撈出影片/圖片，支援標籤篩選。
* **📂 智慧索引**：自動掃描群組 Topic，建立本地資料庫，不用每次都去翻歷史訊息。
* **🔄 一鍵更新**：輸入 `/update`，自動增量掃描所有群組的新資源。
* **🏷️ 自定義標籤**：透過 `tag.json` 設定你自己的分類邏輯（例如：程式教學、健身影片）。
* **📊 活躍度報表**：生成圖表告訴你哪個群組最近更新了，哪個群組已經長草了。

## 🚀 如何使用 (Usage)

### 1. 申請憑證
要使用這個系統，你必須先去 [Telegram 官網](https://my.telegram.org) 申請 API ID。

### 2. 環境設定
請將 `config.py.example` 改名為 `config.py`，並填入你的資訊：
API_ID = 123456
API_HASH = '你的hash'
BOT_TOKEN = '你的bot_token' (跟 @BotFather 申請)

### 3. 啟動
建議使用 v2_integrated_bot 版本，功能最完整

⚠️ 免責聲明 (Disclaimer)
本專案僅供程式技術研究與個人學術用途 (如：資料結構練習、API 串接測試)。

使用者應遵守 Telegram 官方的使用條款 (ToS)。

請勿使用本工具散布版權內容或進行大規模自動化濫用操作。
