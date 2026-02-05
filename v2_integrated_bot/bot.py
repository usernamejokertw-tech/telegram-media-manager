import random
import asyncio
import sys
from telethon import TelegramClient, events, Button
import scanner_lib  # 匯入工具庫
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
STATUS_FILE = 'scan_status.json'

# --- 初始化雙客戶端 ---
user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
bot_client = TelegramClient(BOT_SESSION, API_ID, API_HASH)

# --- 全域變數 ---
user_states = {}
bot_info = None

# 資料容器 (會在 load_data 中初始化)
MEDIA_INDEX = []
FAVORITES = []
TAG_DATA = {}
SEARCH_INDEX_ALL = {}
SEARCH_INDEX_FAV = {}

# --- 資料讀寫與索引 ---
def load_data():
    """從檔案重新載入所有資料並建立索引 (確保與 Scanner 同步)"""
    global MEDIA_INDEX, FAVORITES, TAG_DATA
    global SEARCH_INDEX_ALL, SEARCH_INDEX_FAV
    
    MEDIA_INDEX = scanner_lib.load_json(MEDIA_FILE)
    FAVORITES = scanner_lib.load_json(FAV_FILE)
    
    # 讀取 Tag 並過濾掉 // 後面的註解
    raw_tags = scanner_lib.load_json(TAG_FILE)
    TAG_DATA = {}
    
    for major, minors in raw_tags.items():
        TAG_DATA[major] = {}
        for minor, keys in minors.items():
            clean_keys = []
            for k in keys:
                clean_k = k.split('//')[0].strip()
                clean_keys.append(clean_k)
            TAG_DATA[major][minor] = clean_keys

    # 重建索引
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

load_data() # 初始載入

def get_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            "step": "start", 
            "mode": "all", 
            "minors": set(), 
            "played_groups": [],     
            "selected_ids": set(),   
            "last_bot_msg_ids": [],
            "adding_mode": False,    
            "added_temp": [],         
            "refresh_selected": set()
        }
    return user_states[user_id]

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

# --- 輔助函式 ---
def get_tag_count(mode, major, minor=None):
    index = SEARCH_INDEX_ALL if mode == 'all' else SEARCH_INDEX_FAV
    target_keys = []
    if minor:
        target_keys = TAG_DATA.get(major, {}).get(minor, [])
    else:
        for m_list in TAG_DATA.get(major, {}).values():
            target_keys.extend(m_list)     
    count = 0
    for k in target_keys:
        if k in index: count += len(index[k])
    return count

def get_visual_width(s):
    """計算字串的視覺寬度 (中日韓=2, 英數=1)"""
    width = 0
    for char in s:
        width += 2 if ord(char) > 255 else 1
    return width

def format_fixed_topic(s, limit_width=8, total_width=10):
    """格式化 Topic 名稱 (固定寬度，超過截斷)"""
    current_width = get_visual_width(s)
    if current_width > limit_width:
        temp_s = ""; w = 0
        for char in s:
            cw = 2 if ord(char) > 255 else 1
            if w + cw + 2 > limit_width: break
            temp_s += char; w += cw
        s = temp_s + ".."; current_width = get_visual_width(s)
    padding = total_width - current_width
    return s + " " * (padding if padding > 0 else 0)

async def generate_review_table(sort_mode='date'):
    """生成群組活躍度報表"""
    status_data = scanner_lib.load_json(STATUS_FILE)
    if not status_data: return "⚠️ 無任何掃描紀錄。"

    topic_counts = {}
    if sort_mode == 'count':
        current_media = scanner_lib.load_json(MEDIA_FILE)
        for item in current_media:
            key = (item['group_id'], item['topic'])
            topic_counts[key] = topic_counts.get(key, 0) + 1

    groups_columns = {} 
    
    for chat_id_str, data in status_data.items():
        chat_id = int(chat_id_str)
        title = data.get("title", f"Group {chat_id}")
        topic_map = data.get("topic_map", {})
        topic_last_ids = data.get("topic_last_ids", {})
        
        topic_objs = []
        all_known_topics = set(list(topic_map.keys()) + list(topic_last_ids.keys()))
        
        for t_id_str in all_known_topics:
            if t_id_str == "0": continue
            t_id = int(t_id_str)
            t_name = topic_map.get(t_id_str, "Unknown")
            last_id = int(topic_last_ids.get(t_id_str, 0))
            count = topic_counts.get((chat_id, t_id), 0)
            topic_objs.append({'name': t_name, 'last_id': last_id, 'count': count})
        
        if sort_mode == 'date':
            topic_objs.sort(key=lambda x: x['last_id'], reverse=True)
        else:
            topic_objs.sort(key=lambda x: (x['count'], x['last_id']), reverse=True)
        
        display_list = [format_fixed_topic(obj['name']) for obj in topic_objs]
        clean_title = format_fixed_topic(title, limit_width=12, total_width=14)
        groups_columns[clean_title] = display_list

    if not groups_columns: return "無活躍資料。"

    # 繪製表格
    final_headers = []
    final_columns = []
    for raw_title, items in groups_columns.items():
        final_headers.append(format_fixed_topic(raw_title.strip(), 8, 10)) 
        final_columns.append(items)
    
    columns_data = [groups_columns[h] for h in list(groups_columns.keys())]
    max_rows = max(len(col) for col in columns_data) if columns_data else 0

    table_str = "```\n"
    header_row = ""
    for h in final_headers: header_row += h + "| "
    table_str += header_row.rstrip("| ") + "\n"

    sep_row = ""
    for _ in final_headers: sep_row += "-"*10 + "+-"
    table_str += sep_row.rstrip("+-") + "\n"

    for r in range(max_rows):
        row_str = ""
        for c in range(len(final_columns)):
            col = final_columns[c]
            val = col[r] if r < len(col) else " "*10
            row_str += val + "| "
        table_str += row_str.rstrip("| ") + "\n"
    return table_str + "```"

# ==========================
#      Bot 指令邏輯
# ==========================

@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.respond(
        "👋 **歡迎使用整合助理**\n\n"
        "🎬 **/video** - 隨機播放與收藏\n"
        "📊 **/record** - 群組活躍度報表\n"
        "🔄 **/update** - 立即同步所有群組 (增量)\n"
        "🛠️ **/refresh** - 群組維護 (全量/修復)\n"
        "➕ **/add** - 開啟/關閉 監控錄入模式\n"
        "❌ **/close** - 安全關閉系統"
    )

@bot_client.on(events.NewMessage(pattern='/video'))
async def video_handler(event):
    global bot_info
    if not bot_info: bot_info = await bot_client.get_me()
    buttons = [
        [Button.inline("🎲 全庫隨機", data="menu_all")],
        [Button.inline("⭐ 我的收藏", data="menu_fav")]
    ]
    await event.respond(f"🎬 **影音中心**\n請選擇模式：", buttons=buttons)

@bot_client.on(events.NewMessage(pattern='/record'))
async def record_handler(event):
    msg = await event.respond("📊 正在生成報表...")
    table_text = await generate_review_table(sort_mode='date')
    buttons = [
        [Button.inline("🕒 最新 (目前)", data="rec_sort_date"), Button.inline("🔢 數量", data="rec_sort_count")],
        [Button.inline("❌ 關閉", data="close_menu")]
    ]
    await msg.edit(f"📊 **群組 Topic 活躍度排行**\n(排序: 最新訊息)\n\n{table_text}", buttons=buttons)

@bot_client.on(events.NewMessage(pattern='/add'))
async def add_handler(event):
    user_id = event.sender_id
    state = get_state(user_id)
    if not state['adding_mode']:
        state['adding_mode'] = True
        state['added_temp'] = []
        await event.respond("🟢 **監控錄入模式：已開啟**\n請轉傳群組連結給我。")
    else:
        state['adding_mode'] = False
        count = len(state['added_temp'])
        msg = f"🔴 **模式已關閉**\n本次記錄 {count} 個 ID。"
        if count > 0: msg += "\n請輸入 `/update` 進行掃描。"
        await event.respond(msg)

@bot_client.on(events.NewMessage)
async def link_listener(event):
    state = get_state(event.sender_id)
    if not state.get('adding_mode') or event.text.startswith('/'): return
    if 't.me/' in event.text:
        chat_id, title = await scanner_lib.resolve_link_to_id(user_client, event.text)
        if chat_id:
            status_data = scanner_lib.load_json(STATUS_FILE)
            str_id = str(chat_id)
            if str_id not in status_data:
                status_data[str_id] = {"title": title, "last_id": 0}
                scanner_lib.save_json(STATUS_FILE, status_data)
                state['added_temp'].append(title)
                await event.reply(f"✅ 已鎖定：`{chat_id}` ({title})")
            else:
                await event.reply(f"⚠️ 已在名單中：**{status_data[str_id].get('title')}**")
        else:
            await event.reply("❌ 無法解析連結。")

@bot_client.on(events.NewMessage(pattern='/update'))
async def update_handler(event):
    status_data = scanner_lib.load_json(STATUS_FILE)
    if not status_data:
        await event.respond("⚠️ 名單為空，請先使用 `/add`。")
        return
    msg = await event.respond("⏳ **正在同步所有群組...**")
    total_added = 0; report_lines = []
    for chat_id_str, data in status_data.items():
        try:
            added, line = await scanner_lib.run_incremental_scan(user_client, int(chat_id_str), data.get('title'))
            if added > 0: total_added += added; report_lines.append(line)
        except Exception as e: print(f"Error: {e}")
    load_data()
    final_text = f"✅ **同步完成！**\n總計新增: {total_added} 則"
    if report_lines: final_text += "\n\n" + "\n".join(report_lines)
    await msg.edit(final_text)

async def show_refresh_menu(event, user_id):
    state = get_state(user_id)
    status_data = scanner_lib.load_json(STATUS_FILE)
    buttons = []
    for cid, data in status_data.items():
        title = data.get('title', cid)
        mark = "✅" if cid in state['refresh_selected'] else "⬜"
        buttons.append([Button.inline(f"{mark} {title}", data=f"refresh_toggle_{cid}")])
    count = len(state['refresh_selected'])
    ctrl_row = [Button.inline("❌ 關閉", data="close_menu")]
    if count > 0: ctrl_row.append(Button.inline(f"🚀 執行 ({count})", data="refresh_confirm"))
    buttons.append(ctrl_row)
    try: await event.edit("🔧 **群組維護選單**", buttons=buttons)
    except: await event.respond("🔧 **群組維護選單**", buttons=buttons)

@bot_client.on(events.NewMessage(pattern='/refresh'))
async def refresh_handler(event):
    get_state(event.sender_id)['refresh_selected'] = set()
    await show_refresh_menu(event, event.sender_id)

@bot_client.on(events.NewMessage(pattern='/close'))
async def close_handler(event):
    if event.sender_id != (await user_client.get_me()).id: return
    global bot_info
    if not bot_info: bot_info = await bot_client.get_me()
    await event.respond("👋 正在清理版面並關閉系統...")
    try:
        msg_ids = [m.id async for m in user_client.iter_messages(bot_info.id, limit=100)]
        if msg_ids: await user_client.delete_messages(bot_info.id, msg_ids)
    except: pass
    await user_client.disconnect()
    await bot_client.disconnect()
    sys.exit(0)

# ==========================
#      Callback 處理
# ==========================
@bot_client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    state = get_state(user_id)
    
    if data.startswith('refresh_toggle_'):
        cid = data.split('_')[2]
        if cid in state['refresh_selected']: state['refresh_selected'].remove(cid)
        else: state['refresh_selected'].add(cid)
        await show_refresh_menu(event, user_id)

    elif data == 'refresh_confirm':
        selected_ids = list(state['refresh_selected'])
        if not selected_ids: return
        total = len(selected_ids)
        await event.edit(f"🚀 **準備維護 {total} 個群組...**")
        final_report = "📊 **維護報告**\n\n"
        for index, cid_str in enumerate(selected_ids, 1):
            title = scanner_lib.load_json(STATUS_FILE).get(cid_str, {}).get('title', cid_str)
            try:
                await event.edit(f"⏳ ({index}/{total}) 維護中：**[{title}]** ...")
                final_report += await scanner_lib.run_full_scan(user_client, int(cid_str), title) + "\n---\n"
                load_data()
            except Exception as e: final_report += f"❌ **[{title}]** 失敗: {e}\n"
        await event.edit(final_report + "\n✅ 完成。")

    elif data in ['menu_all', 'menu_fav', 'back_to_major']:
        if data == 'menu_all': state['mode'] = 'all'
        if data == 'menu_fav': state['mode'] = 'fav'
        state['step'] = 'major'; state['minors'] = set()
        mode_text = "全庫隨機" if state['mode'] == 'all' else "收藏夾"
        btn_list = []
        for t in TAG_DATA.keys():
            count = get_tag_count(state['mode'], t)
            btn_list.append(Button.inline(f"{t} ({count})", data=f"major_{t}"))
        rows = list(chunks(btn_list, 3))
        rows.append([Button.inline("🔙 回首頁", data="home")])
        await event.edit(f"📂 **[{mode_text}] 請選擇主分類**", buttons=rows)

    elif data == 'home': await start_handler(event)

    elif data.startswith('major_'):
        state['major'] = data.split('_', 1)[1]; state['step'] = 'minor'
        await show_minor_menu(event, user_id, state['major'])

    elif data.startswith('toggle_tag_'):
        tag = data.split('_', 2)[2]
        if tag in state['minors']: state['minors'].remove(tag)
        else: state['minors'].add(tag)
        await show_minor_menu(event, user_id, state['major'])

    elif data == 'confirm_selection':
        if not state['minors']: return await event.answer("⚠️ 請選擇標籤！", alert=True)
        await event.edit("⏳ **運送影片中...**"); await execute_random_play(user_id)

    elif data == 'play_again':
        await event.delete(); await execute_random_play(user_id)

    elif data in ['panel_fav', 'panel_del']:
        state['selected_ids'] = set()
        await show_action_menu(event, user_id, data.split('_')[1])
    
    elif data == 'panel_link': await show_link_menu(event, user_id)

    elif data.startswith('toggle_act_'):
        parts = data.split('_'); unique_id = f"{parts[3]}_{parts[4]}"
        if unique_id in state['selected_ids']: state['selected_ids'].remove(unique_id)
        else: state['selected_ids'].add(unique_id)
        await show_action_menu(event, user_id, parts[2])

    elif data == 'exec_fav':
        if await process_items(user_id, 'fav') > 0:
            scanner_lib.save_json(FAV_FILE, FAVORITES); load_data()
        await event.answer("✅ 已收藏！", alert=True); await show_control_panel(event.chat_id, user_id)

    elif data == 'exec_del':
        if not state['selected_ids']: return await event.answer("⚠️ 未選擇項目")
        await event.edit("⚠️ **確定刪除？**", buttons=[[Button.inline("❌ 取消", data="panel_del"), Button.inline("🗑️ 確認", data="confirm_real_del")]])

    elif data == 'confirm_real_del':
        await event.edit("⏳ 刪除中...")
        count = await process_items(user_id, 'del')
        scanner_lib.save_json(MEDIA_FILE, MEDIA_INDEX); scanner_lib.save_json(FAV_FILE, FAVORITES); load_data()
        await event.edit(f"🗑️ 已刪除 {count} 個項目。"); await asyncio.sleep(2); await show_control_panel(event.chat_id, user_id)

    elif data == 'show_panel_home':
        await event.delete(); await show_control_panel(event.chat_id, user_id)

    elif data.startswith('rec_sort_'):
        mode = data.split('_')[2]
        await event.answer("🔄 排序中...")
        table = await generate_review_table(sort_mode=mode)
        btns = [[Button.inline(f"🕒 最新{' (目前)' if mode=='date' else ''}", data="rec_sort_date"), Button.inline(f"🔢 數量{' (目前)' if mode=='count' else ''}", data="rec_sort_count")], [Button.inline("❌ 關閉", data="close_menu")]]
        try: await event.edit(f"📊 **活躍度排行**\n\n{table}", buttons=btns)
        except: pass

    elif data == 'close_menu': await event.delete()

# --- UI 輔助函式 ---
async def show_minor_menu(event, user_id, major):
    state = get_state(user_id)
    minors = list(TAG_DATA[major].keys())
    btns = []
    for m in minors:
        mark = "✅ " if m in state['minors'] else ""
        btns.append(Button.inline(f"{mark}{m} ({get_tag_count(state['mode'], major, m)})", data=f"toggle_tag_{m}"))
    rows = list(chunks(btns, 3))
    rows.append([Button.inline("🔙 上一步", data="back_to_major"), Button.inline(f"▶️ 開始 ({len(state['minors'])})", data="confirm_selection")])
    await event.edit(f"📂 **{major}**", buttons=rows)

async def execute_random_play(user_id, count=5):
    global bot_info
    state = get_state(user_id)
    if state['last_bot_msg_ids']:
        try:
            if not bot_info: bot_info = await bot_client.get_me()
            await user_client.delete_messages(bot_info.id, state['last_bot_msg_ids'])
        except: pass
        state['last_bot_msg_ids'] = []

    target_keys = []
    for m in state['minors']: target_keys.extend(TAG_DATA[state['major']].get(m, []))
    
    idx = SEARCH_INDEX_ALL if state['mode'] == 'all' else SEARCH_INDEX_FAV
    candidates = []
    for k in target_keys:
        if k in idx: candidates.extend(idx[k])
            
    if not candidates: return await bot_client.send_message(user_id, f"⚠️ 找不到影片。")

    grouped = {}
    for item in candidates:
        key = f"grp_{item['grouped_id']}" if item.get('grouped_id') else f"msg_{item['msg_id']}"
        if key not in grouped: grouped[key] = []
        grouped[key].append(item)

    sel_keys = random.sample(list(grouped.keys()), min(len(grouped), count))
    played = []; new_ids = []
    if not bot_info: bot_info = await bot_client.get_me()

    for k in sel_keys:
        items = sorted(grouped[k], key=lambda x: x['msg_id'])
        played.append(items)
        try:
            msgs = await user_client.forward_messages(bot_info.id, [i['msg_id'] for i in items], items[0]['group_id'])
            if not isinstance(msgs, list): msgs = [msgs]
            new_ids.extend([m.id for m in msgs])
            await asyncio.sleep(0.5)
        except: pass

    state['played_groups'] = played
    state['last_bot_msg_ids'] = new_ids
    await show_control_panel(user_id, user_id)

async def show_control_panel(chat_id, user_id):
    btns = [[Button.inline("❤️ 加入收藏", data="panel_fav"), Button.inline("🗑️ 刪除資源", data="panel_del")],
            [Button.inline("🔗 原始連結", data="panel_link")],
            [Button.inline("🔄 再來 5 則", data="play_again"), Button.inline("🔙 重選", data="back_to_major")]]
    await bot_client.send_message(chat_id, "🎮 **資源控制台**", buttons=btns)

async def show_action_menu(event, user_id, action):
    state = get_state(user_id)
    rows = []
    for items in state['played_groups']:
        r_btns = []
        for item in items:
            lbl = f"{item['group'][:3]}-{item['topic_name'][:3]}-{item['msg_id']}"
            uid = f"{item['group_id']}_{item['msg_id']}"
            if uid in state['selected_ids']: lbl = "✅ " + lbl
            r_btns.append(Button.inline(lbl, data=f"toggle_act_{action}_{uid}"))
        rows.append(r_btns)
    confirm = "exec_fav" if action == 'fav' else "exec_del"
    rows.append([Button.inline("🔙 取消", data="show_panel_home"), Button.inline("確認", data=confirm)])
    await event.edit("請選擇項目：", buttons=rows)

async def show_link_menu(event, user_id):
    rows = []
    for items in get_state(user_id)['played_groups']:
        r_btns = []
        for item in items:
            gid = str(item['group_id']).replace('-100', '')
            url = f"https://t.me/c/{gid}/{item['msg_id']}?thread={item['topic']}"
            r_btns.append(Button.url(f"🔗 {item['msg_id']}", url))
        rows.append(r_btns)
    rows.append([Button.inline("🔙 返回", data="show_panel_home")])
    await event.edit("🔗 **原始連結**", buttons=rows)

async def process_items(user_id, action):
    state = get_state(user_id)
    targets = state['selected_ids']
    count = 0
    flat = [i for g in state['played_groups'] for i in g]
    for item in flat:
        if f"{item['group_id']}_{item['msg_id']}" in targets:
            if action == 'fav':
                if item not in FAVORITES: FAVORITES.append(item); count += 1
            elif action == 'del':
                try: await user_client.delete_messages(item['group_id'], [item['msg_id']])
                except: pass
                if item in MEDIA_INDEX: MEDIA_INDEX.remove(item)
                if item in FAVORITES: FAVORITES.remove(item)
                count += 1
    return count

async def main():
    print("System Starting...")
    await user_client.start()
    await bot_client.start(bot_token=BOT_TOKEN)
    global bot_info
    bot_info = await bot_client.get_me()
    print("✅ 雙核心系統已啟動")
    await asyncio.gather(user_client.run_until_disconnected(), bot_client.run_until_disconnected())

if __name__ == '__main__':

    asyncio.run(main())
