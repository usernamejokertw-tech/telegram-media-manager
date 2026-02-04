import json
import random
import asyncio
import os
from telethon import TelegramClient, events, Button
import config  # 匯入設定

# 讀取設定檔參數
API_ID = config.API_ID
API_HASH = config.API_HASH
BOT_TOKEN = config.BOT_TOKEN

# 檔案路徑
SESSION_NAME = 'user_session'
BOT_SESSION = 'bot_session'
MEDIA_FILE = 'media_index.json'
FAV_FILE = 'favorites.json'
TAG_FILE = 'tag.json'

# --- 初始化雙客戶端 ---
user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
bot_client = TelegramClient(BOT_SESSION, API_ID, API_HASH)

# --- 全域變數 ---
user_states = {}
bot_info = None

# --- 資料讀寫 ---
def load_json(filename):
    if not os.path.exists(filename):
        return [] if filename in [MEDIA_FILE, FAV_FILE] else {}
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return [] if filename in [MEDIA_FILE, FAV_FILE] else {}

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 載入資料
MEDIA_INDEX = load_json(MEDIA_FILE)
FAVORITES = load_json(FAV_FILE)
TAG_DATA = load_json(TAG_FILE)

# 建立索引
SEARCH_INDEX_ALL = {}
SEARCH_INDEX_FAV = {}

def build_indices():
    """重建記憶體內的搜尋索引"""
    global SEARCH_INDEX_ALL, SEARCH_INDEX_FAV
    SEARCH_INDEX_ALL = {}
    for item in MEDIA_INDEX:
        key = f"{item['group_id']}:{item['topic']}"
        if key not in SEARCH_INDEX_ALL: SEARCH_INDEX_ALL[key] = []
        SEARCH_INDEX_ALL[key].append(item)
        
    SEARCH_INDEX_FAV = {}
    for item in FAVORITES:
        key = f"{item['group_id']}:{item['topic']}"
        if key not in SEARCH_INDEX_FAV: SEARCH_INDEX_FAV[key] = []
        SEARCH_INDEX_FAV[key].append(item)
    print(f"索引重建完成：全庫 {len(SEARCH_INDEX_ALL)} 組 / 收藏 {len(SEARCH_INDEX_FAV)} 組")

build_indices()

def get_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            "step": "start", 
            "mode": "all", 
            "minors": set(), 
            "played_groups": [],     # 儲存本次播放的群組結構
            "selected_ids": set(),   # 儲存使用者勾選的 ID
            "last_bot_msg_ids": []   # 紀錄上次 Bot 發送的訊息 (用於清理)
        }
    return user_states[user_id]

def chunks(lst, n):
    """將列表切割為固定大小的塊 (用於按鈕排列)"""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# --- 輔助函式：計算資源數量 ---
def get_tag_count(mode, major, minor=None):
    """計算某個 Tag 下有多少資源"""
    index = SEARCH_INDEX_ALL if mode == 'all' else SEARCH_INDEX_FAV
    
    target_keys = []
    if minor:
        # 計算單一小 Tag
        target_keys = TAG_DATA.get(major, {}).get(minor, [])
    else:
        # 計算大 Tag (加總所有小 Tag)
        for m_list in TAG_DATA.get(major, {}).values():
            target_keys.extend(m_list)
            
    count = 0
    for k in target_keys:
        if k in index:
            count += len(index[k])
    return count

# --- 表格生成輔助工具 ---
def get_str_width(s):
    """計算字串顯示寬度 (中文字算2格, 英數字算1格)"""
    width = 0
    for char in s:
        if ord(char) > 255: width += 2
        else: width += 1
    return width

def pad_string(s, width):
    """將字串 s 填充到指定顯示寬度"""
    curr_width = get_str_width(s)
    padding = width - curr_width
    return s + " " * (padding if padding > 0 else 0)

async def generate_review_table():
    """生成群組活躍度報表"""
    status_data = load_json('scan_status.json')
    if not status_data: return "⚠️ 無法讀取 scan_status.json"

    groups_data = {}
    
    for chat_id, data in status_data.items():
        topic_map = data.get("topic_map", {})
        topic_last_ids = data.get("topic_last_ids", {})
        
        # 嘗試反查群組名稱
        group_name = f"Group {chat_id}"
        for item in MEDIA_INDEX:
            if str(item['group_id']) == chat_id:
                group_name = item['group']
                break
        
        # 建立 Topic 列表
        topic_list = []
        for t_id, last_msg_id in topic_last_ids.items():
            t_name = topic_map.get(t_id, f"Unknown")
            topic_list.append((t_name, int(last_msg_id)))
        
        # 排序：由新到舊
        topic_list.sort(key=lambda x: x[1], reverse=True)
        
        # 截斷過長字串
        display_list = []
        for name, _ in topic_list:
            clean_name = name[:6] + ".." if len(name) > 6 else name
            display_list.append(clean_name)
            
        groups_data[group_name] = display_list

    if not groups_data: return "無活躍資料。"

    # 繪製表格
    headers = list(groups_data.keys())
    columns = [groups_data[h] for h in headers]
    max_rows = max(len(col) for col in columns) if columns else 0
    
    col_widths = []
    for i, h in enumerate(headers):
        max_w = get_str_width(h)
        for item in columns[i]:
            max_w = max(max_w, get_str_width(item))
        col_widths.append(max_w + 2)

    table_str = "```\n"
    
    # Header
    header_row = ""
    for i, h in enumerate(headers):
        header_row += pad_string(h, col_widths[i]) + "| "
    table_str += header_row.rstrip("| ") + "\n"
    
    # Separator
    sep_row = ""
    for w in col_widths:
        sep_row += "-" * w + "+-"
    table_str += sep_row.rstrip("+-") + "\n"
    
    # Body
    for r in range(max_rows):
        row_str = ""
        for c in range(len(columns)):
            val = columns[c][r] if r < len(columns[c]) else ""
            row_str += pad_string(val, col_widths[c]) + "| "
        table_str += row_str.rstrip("| ") + "\n"
        
    table_str += "```"
    return table_str

# --- Bot UI 邏輯 ---
@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    global bot_info
    if not bot_info: bot_info = await bot_client.get_me()
    sender = await event.get_sender()
    buttons = [
        [Button.inline("🎲 隨機撥放系統", data="menu_all")],
        [Button.inline("⭐ 我的收藏夾", data="menu_fav")],
        [Button.inline("📊 群組活躍回顧", data="menu_review")]
    ]
    await event.respond(f"你好 {sender.first_name}，請選擇模式：", buttons=buttons)

@bot_client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    state = get_state(user_id)
    
    if data in ['menu_all', 'menu_fav', 'back_to_major']:
        if data == 'menu_all': state['mode'] = 'all'
        if data == 'menu_fav': state['mode'] = 'fav'
        state['step'] = 'major'
        state['minors'] = set()
        
        mode_text = "全庫隨機" if state['mode'] == 'all' else "收藏夾"
        major_tags = list(TAG_DATA.keys())
        
        btn_list = []
        for t in major_tags:
            count = get_tag_count(state['mode'], t)
            btn_list.append(Button.inline(f"{t} ({count})", data=f"major_{t}"))
            
        rows = list(chunks(btn_list, 3))
        rows.append([Button.inline("🔙 回首頁", data="home")])
        await event.edit(f"📂 **[{mode_text}] 請選擇主分類**", buttons=rows)

    elif data == 'menu_review':
        await event.answer("正在生成報表...")
        table_text = await generate_review_table()
        buttons = [[Button.inline("🔙 回首頁", data="home")]]
        await event.edit(
            f"📊 **各群組 Topic 活躍度排行**\n(由上至下 = 最近更新 -> 最久未動)\n\n{table_text}", 
            buttons=buttons,
            parse_mode='markdown'
        )
    elif data == 'home':
        await start_handler(event)

    elif data.startswith('major_'):
        selected_major = data.split('_', 1)[1]
        state['major'] = selected_major
        state['step'] = 'minor'
        await show_minor_menu(event, user_id, selected_major)

    elif data.startswith('toggle_tag_'):
        minor_tag = data.split('_', 2)[2]
        if minor_tag in state['minors']: state['minors'].remove(minor_tag)
        else: state['minors'].add(minor_tag)
        await show_minor_menu(event, user_id, state['major'])

    elif data == 'confirm_selection':
        if not state['minors']:
            await event.answer("⚠️ 請至少選擇一個小標籤！", alert=True)
            return
        await event.answer("🚀 搜尋中...")
        await event.edit("⏳ **正在搬運 5 則影片中...**")
        await execute_random_play(user_id, count=5)

    elif data == 'play_again':
        await event.answer("🔄 再來 5 則！")
        await event.delete() 
        await execute_random_play(user_id, count=5)

    elif data == 'panel_fav':
        state['selected_ids'] = set()
        await show_action_menu(event, user_id, action_type="fav")

    elif data == 'panel_del':
        state['selected_ids'] = set()
        await show_action_menu(event, user_id, action_type="del")
    
    elif data == 'panel_link':
        await show_link_menu(event, user_id)

    elif data.startswith('toggle_act_'):
        parts = data.split('_')
        action = parts[2]
        unique_id = f"{parts[3]}_{parts[4]}"
        
        if unique_id in state['selected_ids']:
            state['selected_ids'].remove(unique_id)
        else:
            state['selected_ids'].add(unique_id)
        await show_action_menu(event, user_id, action_type=action)

    elif data == 'exec_fav':
        count = await process_items(user_id, 'fav')
        if count > 0:
            save_json(FAV_FILE, FAVORITES)
            build_indices()
        await event.answer(f"✅ 已收藏 {count} 個項目！", alert=True)
        await show_control_panel(event.chat_id, user_id) 

    elif data == 'exec_del':
        if not state['selected_ids']:
            await event.answer("⚠️ 未選擇項目")
            return
        await event.edit("⚠️ **確定要刪除嗎？**", buttons=[
            [Button.inline("❌ 取消", data="panel_del"), Button.inline("🗑️ 確認刪除", data="confirm_real_del")]
        ])

    elif data == 'confirm_real_del':
        await event.edit("⏳ 刪除中...")
        count = await process_items(user_id, 'del')
        
        save_json(MEDIA_FILE, MEDIA_INDEX)
        save_json(FAV_FILE, FAVORITES)
        build_indices()
        
        await event.edit(f"🗑️ 已刪除 {count} 個項目。")
        await asyncio.sleep(2)
        await show_control_panel(event.chat_id, user_id)

    elif data == 'show_panel_home':
        await event.delete()
        await show_control_panel(event.chat_id, user_id)

async def show_minor_menu(event, user_id, major_tag):
    state = get_state(user_id)
    all_minors = list(TAG_DATA[major_tag].keys())
    btn_list = []
    for m in all_minors:
        count = get_tag_count(state['mode'], major_tag, m)
        prefix = "✅ " if m in state['minors'] else ""
        btn_list.append(Button.inline(f"{prefix}{m} ({count})", data=f"toggle_tag_{m}"))
    
    rows = list(chunks(btn_list, 3))
    mode_str = "全庫" if state['mode'] == 'all' else "收藏"
    rows.append([
        Button.inline("🔙 上一步", data="back_to_major"),
        Button.inline(f"▶️ 開始 ({len(state['minors'])})", data="confirm_selection")
    ])
    await event.edit(f"📂 模式：{mode_str} > **{major_tag}**", buttons=rows)

async def execute_random_play(user_id, count=5):
    state = get_state(user_id)
    
    # 1. 自動清理上一輪的 Bot 訊息
    if state['last_bot_msg_ids']:
        try:
            global bot_info
            if not bot_info: bot_info = await bot_client.get_me()
            await user_client.delete_messages(
                entity=bot_info.id, 
                message_ids=state['last_bot_msg_ids']
            )
        except Exception as e:
            print(f"清理舊訊息失敗: {e}")
        state['last_bot_msg_ids'] = []

    # 2. 搜尋邏輯
    major = state['major']; minors = state['minors']; mode = state['mode']
    current_index = SEARCH_INDEX_ALL if mode == 'all' else SEARCH_INDEX_FAV
    
    target_keys = []
    for m in minors:
        keys = TAG_DATA[major].get(m, [])
        target_keys.extend(keys)
    
    candidate_media = []
    for k in target_keys:
        if k in current_index: candidate_media.extend(current_index[k])
            
    if not candidate_media:
        await bot_client.send_message(user_id, f"⚠️ 找不到影片。")
        return

    # 3. 分組與隨機
    grouped_candidates = {}
    for item in candidate_media:
        g_id = item.get('grouped_id')
        msg_id = item['msg_id']
        unique_key = f"grp_{g_id}" if g_id else f"msg_{msg_id}"
        if unique_key not in grouped_candidates: grouped_candidates[unique_key] = []
        grouped_candidates[unique_key].append(item)

    all_keys = list(grouped_candidates.keys())
    selected_keys = random.sample(all_keys, count) if len(all_keys) >= count else all_keys
    
    # 4. 排序與發送
    played_groups = [] 
    new_sent_msg_ids = []
    
    if not bot_info: bot_info = await bot_client.get_me()
    
    for key in selected_keys:
        items = grouped_candidates[key]
        items.sort(key=lambda x: x['msg_id'])
        played_groups.append(items)
        msg_ids = [i['msg_id'] for i in items]
        from_chat = items[0]['group_id']
        
        try:
            sent_msgs = await user_client.forward_messages(entity=bot_info.id, messages=msg_ids, from_peer=from_chat)
            if not isinstance(sent_msgs, list):
                sent_msgs = [sent_msgs]
            for m in sent_msgs:
                new_sent_msg_ids.append(m.id)
            await asyncio.sleep(0.5) 
        except Exception as e: print(f"Error: {e}")

    state['played_groups'] = played_groups
    state['last_bot_msg_ids'] = new_sent_msg_ids
    await show_control_panel(user_id, user_id)

async def show_control_panel(chat_id, user_id):
    buttons = [
        [Button.inline("❤️ 加入收藏", data="panel_fav"), Button.inline("🗑️ 刪除資源", data="panel_del")],
        [Button.inline("🔗 查看原始連結", data="panel_link")],
        [Button.inline("🔄 再來 5 則", data="play_again"), Button.inline("🔙 重選分類", data="back_to_major")]
    ]
    await bot_client.send_message(chat_id, "🎮 **資源控制台**", buttons=buttons)

async def show_action_menu(event, user_id, action_type):
    state = get_state(user_id)
    groups = state['played_groups']
    rows = []
    
    for items in groups:
        row_btns = []
        for item in items:
            g_id = item['group_id']
            m_id = item['msg_id']
            unique_id = f"{g_id}_{m_id}"
            
            label = f"{item['group'][:3]}-{item['topic_name'][:3]}-{m_id}"
            if unique_id in state['selected_ids']:
                label = "✅ " + label
            
            row_btns.append(Button.inline(label, data=f"toggle_act_{action_type}_{unique_id}"))
        rows.append(row_btns) 
    
    confirm_data = "exec_fav" if action_type == 'fav' else "exec_del"
    confirm_text = "❤️ 確認收藏" if action_type == 'fav' else "🗑️ 確認刪除"
    rows.append([Button.inline("🔙 取消", data="show_panel_home"), Button.inline(confirm_text, data=confirm_data)])
    
    title = "請選擇要 **收藏** 的項目：" if action_type == 'fav' else "請選擇要 **刪除** 的項目："
    await event.edit(title, buttons=rows)

async def show_link_menu(event, user_id):
    state = get_state(user_id)
    groups = state['played_groups']
    rows = []
    
    for items in groups:
        row_btns = []
        for item in items:
            raw_gid = str(item['group_id'])
            clean_gid = raw_gid[4:] if raw_gid.startswith('-100') else raw_gid
            url = f"https://t.me/c/{clean_gid}/{item['msg_id']}"
            if item['topic'] and item['topic'] not in [0, 1]:
                url += f"?thread={item['topic']}"
            
            label = f"🔗 {item['msg_id']}"
            row_btns.append(Button.url(label, url=url))
        rows.append(row_btns)
        
    rows.append([Button.inline("🔙 返回控制台", data="show_panel_home")])
    await event.edit("🔗 **原始訊息連結** (按行分組)", buttons=rows)

async def process_items(user_id, action):
    state = get_state(user_id)
    target_ids = state['selected_ids']
    count = 0
    all_items_flat = [item for group in state['played_groups'] for item in group]
    selected_items = [
        item for item in all_items_flat 
        if f"{item['group_id']}_{item['msg_id']}" in target_ids
    ]
    
    for item in selected_items:
        if action == 'fav':
            if item not in FAVORITES:
                FAVORITES.append(item)
                count += 1
        elif action == 'del':
            try:
                await user_client.delete_messages(entity=item['group_id'], message_ids=[item['msg_id']])
            except: pass
            if item in MEDIA_INDEX: MEDIA_INDEX.remove(item)
            if item in FAVORITES: FAVORITES.remove(item)
            count += 1
    return count

@bot_client.on(events.NewMessage(pattern='/close'))
async def close_handler(event):
    me = await user_client.get_me()
    sender = await event.get_sender()
    if sender.id != me.id: return

    await event.respond("💥 收到自毀指令。正在清除對話並關閉系統...")
    
    global bot_info
    if not bot_info: bot_info = await bot_client.get_me()

    try:
        print(f"正在移除與 Bot ({bot_info.id}) 的對話紀錄...")
        await user_client.delete_dialog(bot_info.id)
        print("✅ 對話紀錄已清除。")
    except Exception as e:
        print(f"清除對話失敗: {e}")

    print("👋 系統正在強制關閉...")
    os._exit(0)

async def main():
    print("啟動中...")
    await user_client.start()
    await bot_client.start(bot_token=BOT_TOKEN)
    global bot_info
    bot_info = await bot_client.get_me()
    print("✅ 啟動完成")
    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected()
    )

if __name__ == '__main__':
    asyncio.run(main())