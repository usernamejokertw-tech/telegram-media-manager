import json
import os
import asyncio
from collections import defaultdict
from telethon import TelegramClient, events, utils
from telethon.tl.types import MessageService, MessageActionTopicCreate
from telethon.tl.functions.messages import GetForumTopicsRequest
import config  # 匯入設定

# 讀取設定檔參數
API_ID = config.API_ID
API_HASH = config.API_HASH
SESSION_NAME = 'user_session'
MEDIA_FILE = 'media_index.json'    # 媒體資料庫
STATUS_FILE = 'scan_status.json'   # 狀態與 Topic 對照表

# 支援的副檔名 (白名單)
VALID_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic'
}

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# --- 檔案讀寫工具 (File I/O) ---
def load_json(filename):
    """讀取 JSON，若檔案不存在則回傳預設空值"""
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {} if filename == STATUS_FILE else []

def save_json(filename, data):
    """寫入 JSON，強制使用 UTF-8 與縮排"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_file_ext(msg):
    """取得檔案副檔名"""
    if msg.file:
        return utils.get_extension(msg.file)
    return ""

def is_target_media(msg):
    """判斷訊息是否為目標媒體 (Video/Photo)"""
    media_type = None; ext = ""
    if msg.photo: media_type = "photo"
    elif msg.video: media_type = "video"
    elif msg.document:
        ext = get_file_ext(msg)
        mime = msg.file.mime_type or ""
        if ext and ext.lower() in VALID_EXTENSIONS:
            media_type = "video" if ext.lower() in ['.mp4', '.mkv', '.avi', '.mov'] else "photo"
        elif mime.startswith(('video/', 'image/')):
            media_type = "video" if mime.startswith('video/') else "photo"
    return media_type, ext

# --- Topic 管理核心 (Topic Management) ---
async def get_topic_map(chat_entity, chat_id, force_refresh=False):
    """
    取得 Topic ID 對應名稱的 Map
    邏輯: 優先讀快取 -> (若強制刷新或快取無) 呼叫 API -> (若 API 失敗) 掃描歷史 Service Msg
    """
    topic_map = {}
    status_data = load_json(STATUS_FILE)
    
    # 從快取載入舊資料
    cached_map = status_data.get(str(chat_id), {}).get("topic_map", {})
    if cached_map:
        topic_map.update(cached_map)

    # 如果不需要強制刷新，且快取有資料，直接回傳
    if not force_refresh and cached_map:
        if "1" in topic_map: topic_map["0"] = topic_map["1"]
        return topic_map

    print("🔡 正在更新 Topic 列表 (API)...")
    api_success = False
    
    try:
        input_channel = await client.get_input_entity(chat_entity)
        offset = 0
        while True:
            # 抓取所有 Topics
            result = await client(GetForumTopicsRequest(
                input_channel, None, 0, offset, 100, ""
            ))
            if not result.topics: break
            
            for t in result.topics:
                topic_map[str(t.id)] = t.title
            
            offset = result.topics[-1].id
            if len(result.topics) < 100: break
        
        api_success = True
        print(f"✅ API 獲取成功，共 {len(topic_map)} 個 Topic。")
    except Exception as e:
        print(f"⚠️ API 獲取失敗: {e}")

    # 若 API 失敗，備案：掃描歷史訊息
    if not api_success:
        print("🔍 進入備援模式：掃描歷史訊息建立 Topic Map...")
        async for message in client.iter_messages(chat_id):
            if isinstance(message, MessageService) and isinstance(message.action, MessageActionTopicCreate):
                t_id = str(message.action.id)
                topic_map[t_id] = message.action.title

    # 邏輯修正：ID 0 和 1 都是 General
    if "1" in topic_map:
        topic_map["0"] = topic_map["1"]
    else:
        topic_map["0"] = "General"
        topic_map["1"] = "General"

    return topic_map

# --- 指令 1: /scan (維護模式：僅改名與清理) ---
@client.on(events.NewMessage(pattern='/scan'))
async def maintenance_scan_handler(event):
    if not event.is_group: return
    chat = await event.get_chat()
    chat_title = chat.title
    chat_id = chat.id
    str_chat_id = str(chat_id)

    msg = await event.respond(f"🛠️ **維護模式啟動** [{chat_title}]\n1. 更新 Topic 名稱\n2. 清理已刪除的檔案\n⚠️ 此模式**不會**新增影片。")

    # 1. 強制刷新 Topic Map
    topic_map = await get_topic_map(chat, chat_id, force_refresh=True)
    
    # 2. 載入資料
    media_data = load_json(MEDIA_FILE)
    status_data = load_json(STATUS_FILE)
    
    other_group_data = [item for item in media_data if item['group_id'] != chat_id]
    current_group_data = [item for item in media_data if item['group_id'] == chat_id]
    
    # 建立舊資料索引
    old_data_map = {item['msg_id']: item for item in current_group_data}
    
    retained_data = []
    topic_name_changes = {} 
    updated_count = 0
    latest_msg_id = 0

    print(f"🔍 開始維護掃描: {chat_title}")

    # 3. 遍歷歷史訊息
    async for message in client.iter_messages(chat_id):
        if message.id > latest_msg_id: latest_msg_id = message.id
        
        # 只處理舊資料庫中有的 (不新增)
        if message.id not in old_data_map:
            continue
            
        item = old_data_map[message.id]
        
        topic_id = 0
        if message.reply_to:
            topic_id = message.reply_to.reply_to_top_id or message.reply_to.reply_to_msg_id or 0
        if topic_id == 0: topic_id = 1

        current_topic_name = topic_map.get(str(topic_id), f"Unknown ({topic_id})")

        # 檢查名稱變更
        old_topic_name = item.get('topic_name', '')
        if old_topic_name != current_topic_name:
            if str(topic_id) not in topic_name_changes:
                topic_name_changes[str(topic_id)] = f"{old_topic_name} ➝ {current_topic_name}"
            item['topic_name'] = current_topic_name
            updated_count += 1
        
        retained_data.append(item)

    # 4. 存檔
    deleted_count = len(current_group_data) - len(retained_data)
    final_data = other_group_data + retained_data
    save_json(MEDIA_FILE, final_data)
    
    # 更新 Last ID (如果掃描到的比較新)
    current_last_id = status_data.get(str_chat_id, {}).get("last_id", 0)
    if latest_msg_id > current_last_id:
        if str_chat_id not in status_data: status_data[str_chat_id] = {}
        status_data[str_chat_id]["last_id"] = latest_msg_id
        
    status_data[str_chat_id]["topic_map"] = topic_map
    save_json(STATUS_FILE, status_data)

    # 5. 報告
    report = (f"✅ **維護完成**\n"
              f"🗑️ 移除失效: {deleted_count}\n"
              f"📝 檔案改名: {updated_count}\n")
    
    if topic_name_changes:
        report += "\n🏷️ **Topic 名稱變更:**\n"
        for t_id, change_str in topic_name_changes.items():
            report += f"- `{change_str}`\n"
    else:
        report += "(無 Topic 名稱變動)"

    await msg.edit(report)
    print(report)


# --- 指令 2: /index (極速增量模式) ---
@client.on(events.NewMessage(pattern='/index'))
async def incremental_scan_handler(event):
    if not event.is_group: return
    chat = await event.get_chat()
    chat_id = chat.id
    str_chat_id = str(chat_id)

    print(f"🚀 增量掃描: {chat.title}")
    await event.respond(f"🚀 正在進行增量更新...")

    # 1. 讀取狀態
    status_data = load_json(STATUS_FILE)
    media_data = load_json(MEDIA_FILE)
    
    # 先嘗試讀快取 Topic Map
    topic_map = await get_topic_map(chat, chat_id, force_refresh=False)

    chat_status = status_data.get(str_chat_id, {})
    last_id = chat_status.get("last_id", 0)
    
    if last_id == 0:
        existing_ids = [i['msg_id'] for i in media_data if i['group_id'] == chat_id]
        if existing_ids: last_id = max(existing_ids)

    new_records = []
    latest_msg_id = last_id
    added_stats = defaultdict(int)
    
    # 載入各 Topic 的 Last ID (轉成 int 方便比對)
    raw_topic_last = chat_status.get("topic_last_ids", {})
    topic_last_active = {k: int(v) for k, v in raw_topic_last.items()}

    has_refreshed_map = False # 標記本次是否已經因為發現新 Topic 而刷新過

    # 2. 增量遍歷
    async for message in client.iter_messages(chat_id, min_id=last_id, reverse=True):
        if message.id > latest_msg_id: latest_msg_id = message.id
        
        m_type, ext = is_target_media(message)
        if m_type:
            # 解析 Topic
            topic_id = 0
            if message.reply_to:
                topic_id = message.reply_to.reply_to_top_id or message.reply_to.reply_to_msg_id or 0
            if topic_id == 0: topic_id = 1
            str_topic_id = str(topic_id)
            
            # 使用 max() 確保永遠記錄到該 Topic "數字最大" 的 ID
            current_topic_last = topic_last_active.get(str_topic_id, 0)
            if message.id > current_topic_last:
                topic_last_active[str_topic_id] = message.id

            # 自動偵測新 Topic: 若發現 ID 不在目前的 Map 裡，立即刷新
            if str_topic_id not in topic_map and not has_refreshed_map:
                print(f"🆕 發現新 Topic ID ({str_topic_id})，正在同步名稱...")
                topic_map = await get_topic_map(chat, chat_id, force_refresh=True)
                has_refreshed_map = True

            t_name = topic_map.get(str_topic_id, f"Unknown ({topic_id})")

            record = {
                "group": chat.title, "group_id": chat_id,
                "topic": topic_id, "topic_name": t_name,
                "msg_id": message.id, "grouped_id": message.grouped_id,
                "type": m_type, "ext": ext, "date": message.date.isoformat()
            }
            new_records.append(record)
            added_stats[t_name] += 1

    # 3. 存檔
    if new_records:
        media_data.extend(new_records)
        save_json(MEDIA_FILE, media_data)
        
    if str_chat_id not in status_data: status_data[str_chat_id] = {}
    
    status_data[str_chat_id]["last_id"] = latest_msg_id
    status_data[str_chat_id]["topic_map"] = topic_map
    status_data[str_chat_id]["topic_last_ids"] = topic_last_active # 存回更新後的活躍度表
    
    save_json(STATUS_FILE, status_data)

    # 4. 報告
    report = f"✅ **增量更新完成！** (Latest ID: {latest_msg_id})\n"
    if added_stats:
        for t, c in added_stats.items(): report += f"📥 {t}: +{c}\n"
    else: report += "💤 無新資源。\n"

    await event.respond(report)
    print("增量掃描完成。")

@client.on(events.NewMessage(pattern='/exit'))
async def exit_handler(event):
    sender = await event.get_sender()
    me = await client.get_me()
    if sender.id != me.id: return

    await event.respond("👋 收到終止指令，正在安全儲存並關閉連線...")
    print("正在執行安全關閉流程...")
    
    await client.disconnect()

async def main():
    await client.start()
    print("User Client (Scanner) 已啟動。")
    print("  /index - 極速增量 (自動抓新 Topic 名稱 + 修正 Last ID)")
    print("  /scan  - 維護模式 (僅改名與清理)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())