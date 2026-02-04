import json
import os
import re
from collections import defaultdict
from telethon import utils
from telethon.tl.types import MessageService, MessageActionTopicCreate
from telethon.tl.functions.messages import GetForumTopicsRequest

# --- 設定區 (與 Bot 共用) ---
MEDIA_FILE = 'media_index.json'
STATUS_FILE = 'scan_status.json'
VALID_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic'
}

# --- 基礎 I/O ---
def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {} if filename == STATUS_FILE else []

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def is_target_media(msg):
    media_type = None; ext = ""
    if msg.photo: media_type = "photo"
    elif msg.video: media_type = "video"
    elif msg.document:
        ext = utils.get_extension(msg.file)
        mime = msg.file.mime_type or ""
        if ext and ext.lower() in VALID_EXTENSIONS:
            media_type = "video" if ext.lower() in ['.mp4', '.mkv', '.avi', '.mov'] else "photo"
        elif mime.startswith(('video/', 'image/')):
            media_type = "video" if mime.startswith('video/') else "photo"
    return media_type, ext

# --- 核心 ID 處理邏輯 ---
async def resolve_link_to_id(client, link):
    try:
        if '/c/' in link:
            match = re.search(r'/c/(\d+)', link)
            if match:
                raw_id = match.group(1)
                chat_id = int(f"-100{raw_id}")
                print(f"✅ (暴力解析) 捕獲 ID: {chat_id}")
                return chat_id, f"待更新群組 ({raw_id})"
        else:
            try:
                entity = await client.get_entity(link)
                return entity.id, entity.title
            except Exception as e:
                print(f"公開連結解析失敗: {e}")
                pass
    except Exception as e:
        print(f"連結處理發生錯誤: {e}")
    return None, None

# --- Topic Map 工具 ---
async def get_topic_map(client, chat_id, force_refresh=False):
    topic_map = {}
    status_data = load_json(STATUS_FILE)
    str_chat_id = str(chat_id)

    # 讀取快取
    cached_map = status_data.get(str_chat_id, {}).get("topic_map", {})
    if cached_map: topic_map.update(cached_map)

    if not force_refresh and cached_map:
        # 執行時自動補上 "0" 對應，但不存檔
        if "1" in topic_map: topic_map["0"] = topic_map["1"]
        return topic_map

    # API 抓取
    try:
        input_channel = await client.get_input_entity(chat_id)
        offset = 0
        while True:
            result = await client(GetForumTopicsRequest(input_channel, None, 0, offset, 100, ""))
            if not result.topics: break
            for t in result.topics: topic_map[str(t.id)] = t.title
            offset = result.topics[-1].id
            if len(result.topics) < 100: break
    except: pass 

    # 歷史訊息備援
    if not topic_map:
        async for message in client.iter_messages(chat_id):
            if isinstance(message, MessageService) and isinstance(message.action, MessageActionTopicCreate):
                topic_map[str(message.action.id)] = message.action.title

    # 運行時補上 "0"，後續存檔前會移除
    if "1" in topic_map: topic_map["0"] = topic_map["1"]
    else: topic_map["0"] = "General"; topic_map["1"] = "General"
    
    return topic_map

# --- 功能 1: 增量掃描 (Bot /update 使用) ---
async def run_incremental_scan(client, chat_id, chat_title="Group"):
    """
    增量掃描：更新 Last ID，寫入新 Topic (不含 Topic 0)
    """
    try:
        entity = await client.get_entity(chat_id)
        current_title = entity.title
    except:
        current_title = chat_title

    status_data = load_json(STATUS_FILE)
    media_data = load_json(MEDIA_FILE)
    str_chat_id = str(chat_id)

    last_id = status_data.get(str_chat_id, {}).get("last_id", 0)
    if last_id == 0:
        existing = [i['msg_id'] for i in media_data if i['group_id'] == chat_id]
        if existing: last_id = max(existing)

    topic_map = await get_topic_map(client, chat_id)
    topic_last_ids = status_data.get(str_chat_id, {}).get("topic_last_ids", {})
    topic_last_active = {k: int(v) for k, v in topic_last_ids.items()}

    new_records = []
    latest_msg_id = last_id
    added_stats = defaultdict(int) 
    has_refreshed_map = False

    async for message in client.iter_messages(chat_id, min_id=last_id, reverse=True):
        if message.id > latest_msg_id: latest_msg_id = message.id
        
        m_type, ext = is_target_media(message)
        if m_type:
            topic_id = 0
            if message.reply_to:
                topic_id = message.reply_to.reply_to_top_id or message.reply_to.reply_to_msg_id or 0
            if topic_id == 0: topic_id = 1
            
            str_topic = str(topic_id)
            
            if message.id > topic_last_active.get(str_topic, 0):
                topic_last_active[str_topic] = message.id

            if str_topic not in topic_map and not has_refreshed_map:
                print(f"🆕 發現新 Topic ID ({str_topic})，正在同步名稱...")
                topic_map = await get_topic_map(client, chat_id, force_refresh=True)
                has_refreshed_map = True
            
            t_name = topic_map.get(str_topic, f"Unknown ({topic_id})")

            new_records.append({
                "group": current_title,
                "group_id": chat_id,
                "topic": topic_id, "topic_name": t_name,
                "msg_id": message.id, "grouped_id": message.grouped_id,
                "type": m_type, "ext": ext, "date": message.date.isoformat()
            })
            added_stats[t_name] += 1

    if new_records:
        media_data.extend(new_records)
        save_json(MEDIA_FILE, media_data)
    
    # 準備存檔的 Map (移除 key "0")
    map_to_save = topic_map.copy()
    if "0" in map_to_save: del map_to_save["0"]

    if str_chat_id not in status_data: status_data[str_chat_id] = {}
    status_data[str_chat_id]["last_id"] = latest_msg_id
    status_data[str_chat_id]["topic_map"] = map_to_save
    status_data[str_chat_id]["topic_last_ids"] = topic_last_active
    status_data[str_chat_id]["title"] = current_title
    save_json(STATUS_FILE, status_data)

    total_added = sum(added_stats.values())
    report = ""
    if total_added > 0:
        report = f"📂 **[{current_title}]** 總新增: {total_added} 則"
        for t_name, count in added_stats.items():
            report += f"\n  └ {t_name}: +{count}"
    
    return total_added, report

# --- 功能 2: 全量維護 (Bot /refresh 使用) ---
async def run_full_scan(client, chat_id, chat_title):
    """
    全量維護：刪除無效影片、回報改名 Topic，但不更新 Last ID
    """
    try:
        entity = await client.get_entity(chat_id)
        chat_title = entity.title
    except: pass

    # 1. 獲取 Telegram 上存活的 Topic
    live_topic_map = {}
    try:
        input_channel = await client.get_input_entity(chat_id)
        offset = 0
        while True:
            result = await client(GetForumTopicsRequest(input_channel, None, 0, offset, 100, ""))
            if not result.topics: break
            for t in result.topics: live_topic_map[str(t.id)] = t.title
            offset = result.topics[-1].id
            if len(result.topics) < 100: break
    except: 
        live_topic_map = await get_topic_map(client, chat_id, force_refresh=True)

    if "1" in live_topic_map: live_topic_map["0"] = live_topic_map["1"]
    else: live_topic_map["0"] = "General"; live_topic_map["1"] = "General"

    media_data = load_json(MEDIA_FILE)
    status_data = load_json(STATUS_FILE)
    
    other_data = [i for i in media_data if i['group_id'] != chat_id]
    current_data = [i for i in media_data if i['group_id'] == chat_id]
    old_map = {i['msg_id']: i for i in current_data}
    
    retained = []
    updated_names = 0
    topic_name_changes = {}
    
    # 2. 掃描本地檔案是否還在歷史訊息中
    async for message in client.iter_messages(chat_id):
        if message.id not in old_map: continue
        
        item = old_map[message.id]
        
        topic_id = 0
        if message.reply_to:
            topic_id = message.reply_to.reply_to_top_id or message.reply_to.reply_to_msg_id or 0
        if topic_id == 0: topic_id = 1
        
        curr_name = live_topic_map.get(str(topic_id), f"Unknown ({topic_id})")
        old_name = item.get('topic_name', '')

        if old_name != curr_name:
            if str(topic_id) not in topic_name_changes:
                topic_name_changes[str(topic_id)] = f"{old_name} ➝ {curr_name}"
            item['topic_name'] = curr_name
            item['group'] = chat_title 
            updated_names += 1
            
        retained.append(item)
    
    # 3. 計算刪除統計
    retained_ids = {i['msg_id'] for i in retained}
    deleted_stats = defaultdict(int)
    deleted_count = 0
    
    for item in current_data:
        if item['msg_id'] not in retained_ids:
            t_name = item.get('topic_name', 'Unknown')
            deleted_stats[t_name] += 1
            deleted_count += 1

    # 4. 構建最終的 Clean Topic Map
    final_topic_map = live_topic_map.copy()
    used_topic_ids = {str(i['topic']) for i in retained}
    old_status_map = status_data.get(str(chat_id), {}).get("topic_map", {})
    
    for tid in used_topic_ids:
        if tid not in final_topic_map:
            final_topic_map[tid] = old_status_map.get(tid, f"Unknown ({tid})")

    # 5. 清理 Last IDs
    old_last_ids = status_data.get(str(chat_id), {}).get("topic_last_ids", {})
    new_last_ids = {}
    for tid, msg_id in old_last_ids.items():
        if tid in final_topic_map:
            new_last_ids[tid] = msg_id

    # 存檔 (Media & Status)
    save_json(MEDIA_FILE, other_data + retained)
    
    str_chat_id = str(chat_id)
    if str_chat_id not in status_data: status_data[str_chat_id] = {}
    
    if "0" in final_topic_map: del final_topic_map["0"]
    
    status_data[str_chat_id]["topic_map"] = final_topic_map
    status_data[str_chat_id]["topic_last_ids"] = new_last_ids
    status_data[str_chat_id]["title"] = chat_title
    save_json(STATUS_FILE, status_data)
    
    report = f"✅ **[{chat_title}] 維護完成**\n"
    if deleted_count > 0:
        report += f"🗑️ **移除 {deleted_count} 個失效資源**\n"
        for t_name, count in deleted_stats.items():
            report += f"  └ {t_name}: -{count}\n"
    else: report += "🗑️ 無失效資源\n"

    if updated_names > 0: report += f"📝 **更新 {updated_names} 個檔案名稱**\n"
    
    if topic_name_changes:
        report += "\n🏷️ **Topic 名稱變更:**\n"
        for _, change_str in topic_name_changes.items():
            report += f"- `{change_str}`\n"
    
    return report