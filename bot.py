import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
import aiosqlite
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ======================================================
# КОНФИГ
# ======================================================

WORKER_BOT_TOKEN  = "8714366872:AAFmKwU-T2E_JMqDUz_xv23PEko5LeHWfOw"
MANAGER_BOT_TOKEN = "8758406348:AAEjNIPMChEc1gZ3IQlh7aUCShVwutGHOFU"

MANAGER_IDS = [5952683615, 39730332, 8473394162]

UZB_TZ = ZoneInfo("Asia/Tashkent")

DB = "attendance.db"

# ======================================================
# БОТЫ И ДИСПЕТЧЕРЫ
# ======================================================

worker_bot  = Bot(token=WORKER_BOT_TOKEN)
manager_bot = Bot(token=MANAGER_BOT_TOKEN)

worker_dp  = Dispatcher()
manager_dp = Dispatcher()

# ======================================================
# СОСТОЯНИЯ
# ======================================================

user_state    = {}  # {uid: {"emp": emp, "mode": ...}}
manager_state = {}  # {uid: {"mode": ..., "step": ..., ...}}

# ======================================================
# ДАННЫЕ СОТРУДНИКОВ (загружаются из БД)
# ======================================================

employees       = []
emp_by_fullname = {}
emp_by_id       = {}
emp_by_name     = {}

# ======================================================
# БАЗА ДАННЫХ
# ======================================================

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT,
                checkin     TEXT,
                checkout    TEXT,
                late        INTEGER,
                week        TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id      TEXT PRIMARY KEY,
                name    TEXT,
                shift   TEXT,
                off_day TEXT DEFAULT 'None'
            )
        """)
        # Безопасное добавление колонки если её нет
        cur = await db.execute("PRAGMA table_info(employees)")
        cols = [row[1] for row in await cur.fetchall()]
        if "off_day" not in cols:
            await db.execute("ALTER TABLE employees ADD COLUMN off_day TEXT DEFAULT 'None'")
        await db.commit()

        # Дефолтные сотрудники если таблица пустая
        cur = await db.execute("SELECT COUNT(*) FROM employees")
        row = await cur.fetchone()
        if row[0] == 0:
            defaults = [
                ("#A770", "Abdulloh",  "16:00", "None"),
                ("#L470", "Mubina",    "00:00", "None"),
                ("#D370", "Davlat",    "16:00", "None"),
                ("#D870", "Davron",    "08:00", "None"),
                ("#J660", "Laziz",     "08:00", "None"),
                ("#P710", "Ibrohim",   "00:00", "None"),
                ("#J450", "Yusuf",     "16:00", "None"),
                ("#A777", "Bobur",     "08:00", "None"),
                ("#C333", "Abdulaziz", "00:00", "None"),
            ]
            for e in defaults:
                await db.execute("INSERT OR IGNORE INTO employees VALUES (?,?,?,?)", e)
            await db.commit()

async def load_employees_from_db():
    global employees, emp_by_fullname, emp_by_id, emp_by_name
    async with aiosqlite.connect(DB) as db:
        cur  = await db.execute("SELECT id, name, shift, off_day FROM employees")
        rows = await cur.fetchall()
    labels = {
        "08:00": "Day: 08:00 - 16:00",
        "16:00": "Main: 16:00 - 00:00",
        "00:00": "Night: 00:00 - 08:00",
    }
    employees       = [(r[0], r[1], r[2], labels.get(r[2], r[2]), r[3] or "None") for r in rows]
    emp_by_fullname = {f"{e[1]} {e[0]}": e for e in employees}
    emp_by_id       = {e[0]: e for e in employees}
    emp_by_name     = {e[1].lower(): e for e in employees}

# ======================================================
# ХЕЛПЕРЫ
# ======================================================

def now_uzb():
    """Текущее время по Ташкенту (naive для хранения в БД)."""
    return datetime.now(UZB_TZ).replace(tzinfo=None)

def get_month_key(dt):
    return f"{dt.year}-M{dt.month:02d}"

def format_late(minutes):
    if minutes <= 0:
        return "✅ On time"
    h, m = divmod(minutes, 60)
    return f"⏰ {h}h {m}min late" if h > 0 else f"⏰ {m} min late"

def format_duration(minutes):
    if minutes <= 0:
        return "0 min"
    h, m = divmod(minutes, 60)
    if h > 0 and m > 0:
        return f"{h}h {m}min"
    return f"{h}h" if h > 0 else f"{m} min"

def get_shift_times(emp, now):
    """Возвращает (start, end) смены для сотрудника относительно now."""
    shift_hour = int(emp[2].split(":")[0])
    if shift_hour == 8:
        start = now.replace(hour=8,  minute=0, second=0, microsecond=0)
        end   = now.replace(hour=16, minute=0, second=0, microsecond=0)
    elif shift_hour == 16:
        start = now.replace(hour=16, minute=0, second=0, microsecond=0)
        end   = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # Ночная смена 00:00–08:00
        if now.hour >= 20:
            # Вечер — смена начнётся завтра в 00:00
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        elif now.hour < 8:
            # Ночь/утро — смена началась сегодня в 00:00
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            # День (08:00–20:00) — следующая ночная смена завтра в 00:00
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=8)
    return start, end

def calc_late(shift_start, now):
    return max(int((now - shift_start).total_seconds() / 60), 0)

# ======================================================
# КЛАВИАТУРЫ
# ======================================================

def kb_employees():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"{e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def kb_worker_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Check-in"), KeyboardButton(text="📤 Check-out")],
            [KeyboardButton(text="⬅️ Back")],
        ],
        resize_keyboard=True,
    )

def kb_checkout():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"📤 {e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([KeyboardButton(text="⬅️ Back")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def kb_manager_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Report"),       KeyboardButton(text="📋 History")],
            [KeyboardButton(text="💰 Fine Report"),  KeyboardButton(text="📅 Off Days")],
            [KeyboardButton(text="➕ Add Employee"), KeyboardButton(text="❌ Remove Employee")],
        ],
        resize_keyboard=True,
    )

def kb_history():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"📋 {e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([KeyboardButton(text="🔙 Cancel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def kb_remove():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"🗑 {e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    buttons.append([KeyboardButton(text="🔙 Cancel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def kb_offdays():
    """Список сотрудников с их выходными — для просмотра и редактирования."""
    buttons = []
    for e in employees:
        off = e[4] if len(e) > 4 else "None"
        off_label = "🟢 " + off if off not in ("None", "No day off") else "⚪ No day off"
        buttons.append([KeyboardButton(text=f"{e[1]} {e[0]} — {off_label}")])
    buttons.append([KeyboardButton(text="🔙 Cancel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def kb_shifts():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌅 Day (08:00-16:00)")],
            [KeyboardButton(text="🌆 Main (16:00-00:00)")],
            [KeyboardButton(text="🌙 Night (00:00-08:00)")],
            [KeyboardButton(text="🔙 Cancel")],
        ],
        resize_keyboard=True,
    )

def kb_days():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Monday"),    KeyboardButton(text="Tuesday")],
            [KeyboardButton(text="Wednesday"), KeyboardButton(text="Thursday")],
            [KeyboardButton(text="Friday"),    KeyboardButton(text="Saturday")],
            [KeyboardButton(text="Sunday"),    KeyboardButton(text="No day off")],
            [KeyboardButton(text="🔙 Cancel")],
        ],
        resize_keyboard=True,
    )

# ======================================================
# УВЕДОМЛЕНИЯ МЕНЕДЖЕРАМ
# ======================================================

async def notify_managers(text):
    """Отправить сообщение ВСЕМ менеджерам."""
    for cid in MANAGER_IDS:
        try:
            await manager_bot.send_message(cid, text)
        except Exception as e:
            print(f"[ERROR] notify_managers {cid}: {e}")

# ======================================================
# WORKER BOT — ХЭНДЛЕРЫ
# ======================================================

@worker_dp.message(CommandStart())
async def w_start(message: types.Message):
    user_state.pop(message.from_user.id, None)
    await message.answer("👋 Attendance System\n\nSelect employee:", reply_markup=kb_employees())

@worker_dp.message()
async def w_handler(message: types.Message):
    text  = message.text or ""
    uid   = message.from_user.id
    state = user_state.get(uid, {})

    # ── BACK ──────────────────────────────────────────────
    if text == "⬅️ Back":
        user_state.pop(uid, None)
        await message.answer("Select employee:", reply_markup=kb_employees())
        return

    # ── ВЫБОР СОТРУДНИКА ──────────────────────────────────
    emp = emp_by_fullname.get(text)
    if emp:
        user_state[uid] = {"emp": emp}
        await message.answer(
            f"👤 {emp[1]} {emp[0]}\n🕐 Shift: {emp[3]}",
            reply_markup=kb_worker_menu())
        return

    # ── CHECK-IN ──────────────────────────────────────────
    if text == "✅ Check-in":
        emp = state.get("emp")
        if not emp:
            await message.answer("❗ Select employee first.", reply_markup=kb_employees())
            return

        now      = now_uzb()
        time_str = now.strftime("%H:%M")

        # Уже зачекинен?
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "SELECT id FROM attendance WHERE employee_id=? AND checkout IS NULL ORDER BY id DESC LIMIT 1",
                (emp[0],))
            if await cur.fetchone():
                await message.answer(f"⚠️ {emp[1]} already checked in! Check out first.")
                return

        # День отдыха?
        off_day    = emp[4] if len(emp) > 4 else "None"
        today_name = now.strftime("%A")
        if off_day not in ("None", "No day off") and off_day == today_name:
            await message.answer(f"🌴 {emp[1]} has day off today ({today_name})!\nCheck-in not allowed.")
            return

        # Время смены
        shift_start, shift_end = get_shift_times(emp, now)
        if not (shift_start - timedelta(hours=1) <= now <= shift_end):
            await message.answer(
                f"⛔ Check-in not allowed now!\n"
                f"📋 Shift: {emp[3]}\n"
                f"🕐 {shift_start.strftime('%H:%M')} — {shift_end.strftime('%H:%M')}")
            return

        late        = calc_late(shift_start, now)
        week        = get_month_key(now)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        async with aiosqlite.connect(DB) as db:
            await db.execute(
                "INSERT INTO attendance (employee_id, checkin, late, week) VALUES (?,?,?,?)",
                (emp[0], now.isoformat(), late, week))
            await db.commit()
            cur = await db.execute(
                "SELECT SUM(late) FROM attendance WHERE employee_id=? AND week=? AND checkin>=?",
                (emp[0], week, month_start.isoformat()))
            row            = await cur.fetchone()
            total_mo_late  = row[0] or 0

        late_emoji = "🟢" if late <= 15 else "🟡" if late <= 30 else "🔴"
        late_msg   = format_late(late)

        await message.answer(
            f"✅ {emp[1]} checked in\n"
            f"🕒 Time: {time_str}\n"
            f"📋 Shift: {emp[3]}\n"
            f"⏱ {late_msg}\n"
            f"💸 Fine today: ${late}\n"
            f"📊 Monthly late: {format_duration(total_mo_late)}\n"
            f"💰 Monthly fine: ${total_mo_late}")

        await notify_managers(
            f"{late_emoji} CHECK-IN\n\n"
            f"👤 {emp[1]} {emp[0]}\n"
            f"🕒 Time: {time_str}\n"
            f"📋 Shift: {emp[3]}\n"
            f"⏰ {late_msg}\n"
            f"💸 Fine today: ${late}\n"
            f"📊 Monthly late: {format_duration(total_mo_late)}\n"
            f"💰 Monthly fine: ${total_mo_late}")
        return

    # ── CHECK-OUT КНОПКА ──────────────────────────────────
    if text == "📤 Check-out":
        user_state[uid] = {**state, "mode": "checkout"}
        await message.answer("Select employee to check out:", reply_markup=kb_checkout())
        return

    # ── CHECK-OUT ВЫБОР СОТРУДНИКА ────────────────────────
    if text.startswith("📤 "):
        fullname = text[3:].strip()
        emp      = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❗ Employee not found.")
            return

        now      = now_uzb()
        time_str = now.strftime("%H:%M")

        shift_start, shift_end = get_shift_times(emp, now)
        if not (shift_start <= now <= shift_end + timedelta(minutes=30)):
            await message.answer(
                f"⛔ Check-out not allowed now!\n"
                f"📋 Shift: {emp[3]}\n"
                f"🕐 {shift_start.strftime('%H:%M')} — {shift_end.strftime('%H:%M')}")
            return

        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(
                "SELECT id, checkin FROM attendance WHERE employee_id=? AND checkout IS NULL ORDER BY id DESC LIMIT 1",
                (emp[0],))
            row = await cur.fetchone()

            if not row:
                await message.answer(f"❌ {emp[1]} has no active check-in.", reply_markup=kb_checkout())
                return

            record_id, checkin_str = row
            checkin_dt     = datetime.fromisoformat(checkin_str)
            worked_min     = int((now - checkin_dt).total_seconds() / 60)
            worked_h, worked_m = divmod(worked_min, 60)

            early_min = int((shift_end - now).total_seconds() / 60) if now < shift_end else 0
            if early_min >= 60:
                eh, em    = divmod(early_min, 60)
                early_msg = f"\n⚠️ Left {eh}h {em}min early!" if em > 0 else f"\n⚠️ Left {eh}h early!"
            elif early_min > 0:
                early_msg = f"\n⚠️ Left {early_min} min early!"
            else:
                early_msg = ""

            await db.execute(
                "UPDATE attendance SET checkout=? WHERE id=?",
                (now.isoformat(), record_id))
            await db.commit()

        await message.answer(
            f"📤 {emp[1]} checked out\n"
            f"🕒 Time: {time_str}\n"
            f"⏱ Worked: {worked_h}h {worked_m}min{early_msg}",
            reply_markup=kb_employees())

        await notify_managers(
            f"🔴 CHECK-OUT\n\n"
            f"👤 {emp[1]} {emp[0]}\n"
            f"🕒 Time: {time_str}\n"
            f"⏱ Worked: {worked_h}h {worked_m}min{early_msg}")

        user_state.pop(uid, None)
        return

# ======================================================
# MANAGER BOT — ХЭНДЛЕРЫ
# ======================================================

@manager_dp.message(CommandStart())
async def m_start(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        await message.answer("⛔ Access denied.")
        return
    manager_state.pop(message.from_user.id, None)
    await message.answer("👋 Manager Panel\nSelect action:", reply_markup=kb_manager_menu())

@manager_dp.message(Command("report"))
async def m_cmd_report(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        await message.answer("⛔ Access denied.")
        return
    await send_report_to_all(on_demand=True)

@manager_dp.message()
async def m_handler(message: types.Message):
    text = message.text or ""
    uid  = message.from_user.id

    if uid not in MANAGER_IDS:
        await message.answer("⛔ Access denied.")
        return

    state = manager_state.get(uid, {})

    # ── CANCEL ────────────────────────────────────────────
    if text == "🔙 Cancel":
        manager_state.pop(uid, None)
        await message.answer("Main menu:", reply_markup=kb_manager_menu())
        return

    # ── REPORT → всем менеджерам ──────────────────────────
    if text == "📊 Report":
        await send_report_to_all(on_demand=True)
        return

    # ── FINE REPORT → всем менеджерам ────────────────────
    if text == "💰 Fine Report":
        await send_fine_report_to_all()
        return

    # ── HISTORY ───────────────────────────────────────────
    if text == "📋 History":
        manager_state[uid] = {"mode": "history"}
        await message.answer("Select employee:", reply_markup=kb_history())
        return

    if state.get("mode") == "history" and text.startswith("📋 "):
        fullname = text[2:].strip()
        emp      = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❌ Employee not found.")
            return

        now         = now_uzb()
        month       = get_month_key(now)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        async with aiosqlite.connect(DB) as db:
            cur  = await db.execute(
                "SELECT checkin, checkout, late FROM attendance "
                "WHERE employee_id=? AND week=? AND checkin>=? ORDER BY checkin ASC",
                (emp[0], month, month_start.isoformat()))
            rows = await cur.fetchall()

        if not rows:
            await message.answer(f"📭 No records for {emp[1]} this month.", reply_markup=kb_manager_menu())
            manager_state.pop(uid, None)
            return

        lines        = [f"📋 {emp[1]} {emp[0]}", f"🗓 {month_start.strftime('%B %Y')}", "―" * 30]
        total_late   = 0
        total_worked = 0

        for checkin_str, checkout_str, late in rows:
            ci = datetime.fromisoformat(checkin_str)
            co = datetime.fromisoformat(checkout_str) if checkout_str else None
            wm = int((co - ci).total_seconds() / 60) if co else 0
            total_worked += wm
            total_late   += (late or 0)
            lines.append(
                f"\n📅 {ci.strftime('%a %d.%m')}\n"
                f"   In: {ci.strftime('%H:%M')}  "
                f"Out: {co.strftime('%H:%M') if co else 'active'}\n"
                f"   Worked: {wm//60}h {wm%60}min  |  {format_late(late or 0)}\n"
                f"   💸 Fine: ${late or 0}")

        lines += [
            "―" * 30,
            f"📊 Total late: {format_duration(total_late)}",
            f"💰 Total fine: ${total_late}",
            f"⏱ Total worked: {total_worked//60}h {total_worked%60}min",
        ]
        await message.answer("\n".join(lines), reply_markup=kb_manager_menu())
        manager_state.pop(uid, None)
        return

    # ── ADD EMPLOYEE ──────────────────────────────────────
    if text == "➕ Add Employee":
        manager_state[uid] = {"mode": "add", "step": "name"}
        await message.answer("➕ Step 1/4: Enter employee name:")
        return

    if state.get("mode") == "add":
        step = state.get("step")

        if step == "name":
            manager_state[uid] = {"mode": "add", "step": "id", "name": text}
            await message.answer(f"👤 Name: {text}\n\nStep 2/4: Enter ID (e.g. #X123):")
            return

        if step == "id":
            emp_id = text.strip()
            if emp_id in emp_by_id:
                await message.answer(f"❌ ID {emp_id} exists! Enter different ID:")
                return
            manager_state[uid] = {**state, "step": "shift", "id": emp_id}
            await message.answer(
                f"👤 {state['name']}  🆔 {emp_id}\n\nStep 3/4: Select shift:",
                reply_markup=kb_shifts())
            return

        if step == "shift":
            shift_map = {
                "🌅 Day (08:00-16:00)":   ("08:00", "Day: 08:00 - 16:00"),
                "🌆 Main (16:00-00:00)":  ("16:00", "Main: 16:00 - 00:00"),
                "🌙 Night (00:00-08:00)": ("00:00", "Night: 00:00 - 08:00"),
            }
            if text not in shift_map:
                await message.answer("❌ Use the buttons to select shift.")
                return
            shift, label = shift_map[text]
            manager_state[uid] = {**state, "step": "offday", "shift": shift, "label": label}
            await message.answer(
                f"👤 {state['name']}  🆔 {state['id']}  📋 {label}\n\nStep 4/4: Select off day:",
                reply_markup=kb_days())
            return

        if step == "offday":
            valid_days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","No day off"]
            if text not in valid_days:
                await message.answer("❌ Use the buttons to select day.")
                return
            name, emp_id, shift, label = state["name"], state["id"], state["shift"], state["label"]
            new_emp = (emp_id, name, shift, label, text)
            employees.append(new_emp)
            emp_by_fullname[f"{name} {emp_id}"] = new_emp
            emp_by_id[emp_id]                   = new_emp
            emp_by_name[name.lower()]            = new_emp
            async with aiosqlite.connect(DB) as db:
                await db.execute(
                    "INSERT INTO employees (id, name, shift, off_day) VALUES (?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name, shift=excluded.shift, off_day=excluded.off_day",
                    (emp_id, name, shift, text))
                await db.commit()
            manager_state.pop(uid, None)
            await message.answer(
                f"✅ Added!\n👤 {name} {emp_id}\n📋 {label}\n🗓 Off day: {text}",
                reply_markup=kb_manager_menu())
            return

    # ── REMOVE EMPLOYEE ───────────────────────────────────
    if text == "❌ Remove Employee":
        if not employees:
            await message.answer("No employees.", reply_markup=kb_manager_menu())
            return
        manager_state[uid] = {"mode": "remove"}
        await message.answer("Select employee to remove:", reply_markup=kb_remove())
        return

    if state.get("mode") == "remove" and text.startswith("🗑 "):
        fullname = text[2:].strip()
        emp      = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❌ Not found.")
            return
        employees.remove(emp)
        emp_by_fullname.pop(f"{emp[1]} {emp[0]}", None)
        emp_by_id.pop(emp[0], None)
        emp_by_name.pop(emp[1].lower(), None)
        async with aiosqlite.connect(DB) as db:
            await db.execute("DELETE FROM employees WHERE id=?", (emp[0],))
            await db.commit()
        manager_state.pop(uid, None)
        await message.answer(f"✅ Removed: {emp[1]} {emp[0]}", reply_markup=kb_manager_menu())
        return

    # ── OFF DAYS — просмотр и редактирование ─────────────
    if text == "📅 Off Days":
        now   = now_uzb()
        today = now.strftime("%A")
        lines = ["📅 OFF DAYS SCHEDULE", "―" * 30]
        for e in employees:
            off      = e[4] if len(e) > 4 else "None"
            off_show = off if off != "None" else "No day off"
            marker   = "  🔴 TODAY" if off == today else ""
            lines.append(f"👤 {e[1]} {e[0]}\n   📋 {e[3]}\n   🗓 {off_show}{marker}")
        await message.answer("\n\n".join(lines) + "\n\n" + "―"*30 + "\nTap to change off day:", reply_markup=kb_offdays())
        manager_state[uid] = {"mode": "offdays"}
        return

    if state.get("mode") == "offdays":
        emp = None
        for e in employees:
            if text.startswith(f"{e[1]} {e[0]}"):
                emp = e
                break
        if not emp:
            await message.answer("❌ Not found.")
            return
        manager_state[uid] = {"mode": "offdays_pick", "emp": emp}
        off = emp[4] if len(emp) > 4 else "None"
        await message.answer(
            f"👤 {emp[1]} {emp[0]}\n📋 Shift: {emp[3]}\n🗓 Current off day: {off}\n\nSelect new off day:",
            reply_markup=kb_days())
        return

    if state.get("mode") == "offdays_pick":
        valid_days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","No day off"]
        if text not in valid_days:
            await message.answer("❌ Use the buttons.")
            return
        emp = state["emp"]
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE employees SET off_day=? WHERE id=?", (text, emp[0]))
            await db.commit()
        await load_employees_from_db()
        manager_state.pop(uid, None)
        await message.answer(
            f"✅ Updated!\n👤 {emp[1]} {emp[0]}\n🗓 New off day: {text}",
            reply_markup=kb_manager_menu())
        return

    # ── FALLBACK ──────────────────────────────────────────
    await message.answer("Select action:", reply_markup=kb_manager_menu())

# ======================================================
# ОТЧЁТЫ — отправляют ВСЕМ менеджерам
# ======================================================

async def send_report_to_all(on_demand=False):
    now         = now_uzb()
    month       = get_month_key(now)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    label       = " (on demand)" if on_demand else ""

    lines = [
        f"📊 MONTHLY REPORT{label}",
        f"🗓 {month_start.strftime('%B %Y')}",
        "―" * 30,
    ]

    async with aiosqlite.connect(DB) as db:
        for emp in employees:
            cur = await db.execute(
                "SELECT COUNT(*), SUM(late) FROM attendance WHERE employee_id=? AND week=? AND checkin>=?",
                (emp[0], month, month_start.isoformat()))
            row        = await cur.fetchone()
            shifts     = row[0] or 0
            total_late = row[1] or 0

            lines.append(
                f"\n👤 {emp[1]} {emp[0]}\n"
                f"   Shifts: {shifts}  |  Late: {format_duration(total_late)}\n"
                f"   💰 Fine: ${total_late}")

            cur2     = await db.execute(
                "SELECT checkin, late FROM attendance "
                "WHERE employee_id=? AND week=? AND checkin>=? AND late>0 ORDER BY checkin ASC",
                (emp[0], month, month_start.isoformat()))
            day_rows = await cur2.fetchall()
            if day_rows:
                lines.append("   ── Late days ──")
                for checkin_str, late in day_rows:
                    ci = datetime.fromisoformat(checkin_str)
                    lines.append(f"   📅 {ci.strftime('%a %d.%m')}  {ci.strftime('%H:%M')}  +{late}min  💸${late}")

    lines += ["―" * 30, f"📅 {now.strftime('%d.%m.%Y %H:%M')}"]
    text_out = "\n".join(lines)

    await notify_managers(text_out)
    print(f"[INFO] Report sent {now.strftime('%d.%m.%Y %H:%M')}")

async def send_fine_report_to_all():
    now         = now_uzb()
    month       = get_month_key(now)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    lines = [
        "💰 FINE REPORT",
        f"🗓 {month_start.strftime('%B %Y')}",
        "―" * 30,
    ]
    total_all = 0

    async with aiosqlite.connect(DB) as db:
        for emp in employees:
            cur  = await db.execute(
                "SELECT checkin, late FROM attendance WHERE employee_id=? AND week=? AND checkin>=? ORDER BY checkin ASC",
                (emp[0], month, month_start.isoformat()))
            rows       = await cur.fetchall()
            total_late = sum(r[1] or 0 for r in rows)
            total_all += total_late

            if total_late == 0:
                lines.append(f"\n👤 {emp[1]} {emp[0]}\n   ✅ No fines")
                continue

            lines.append(f"\n👤 {emp[1]} {emp[0]}")
            lines.append(f"   Late: {format_duration(total_late)}  💰 ${total_late}")
            for checkin_str, late in rows:
                if not late: continue
                ci = datetime.fromisoformat(checkin_str)
                lines.append(f"   📅 {ci.strftime('%a %d.%m')}  {ci.strftime('%H:%M')}  +{late}min  💸${late}")

    lines += ["―" * 30, f"💰 TOTAL: ${total_all}", f"📅 {now.strftime('%d.%m.%Y %H:%M')}"]
    await notify_managers("\n".join(lines))

# ======================================================
# NO-SHOW CHECKER
# ======================================================

async def check_no_shows():
    alerted = set()
    while True:
        await asyncio.sleep(60)
        now = now_uzb()
        async with aiosqlite.connect(DB) as db:
            for emp in employees:
                shift_start, _ = get_shift_times(emp, now)
                alert_time     = shift_start + timedelta(minutes=30)
                alert_key      = f"{emp[0]}-{shift_start.date()}"
                if not (alert_time <= now <= alert_time + timedelta(minutes=2)):
                    continue
                if alert_key in alerted:
                    continue
                cur = await db.execute(
                    "SELECT id FROM attendance WHERE employee_id=? AND checkin>=?",
                    (emp[0], shift_start.isoformat()))
                if not await cur.fetchone():
                    alerted.add(alert_key)
                    await notify_managers(
                        f"🚨 NO-SHOW!\n\n"
                        f"👤 {emp[1]} {emp[0]}\n"
                        f"📋 Shift: {emp[3]}\n"
                        f"🕐 Started: {shift_start.strftime('%H:%M')}\n"
                        f"⏰ 30 min passed — not checked in!")

# ======================================================
# ЕЖЕМЕСЯЧНЫЙ ОТЧЁТ (автоматически в конце месяца)
# ======================================================

async def monthly_scheduler():
    while True:
        now = now_uzb()
        if now.month == 12:
            next_m = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_m = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = (next_m - timedelta(seconds=1)).replace(hour=23, minute=59, second=0, microsecond=0)
        wait     = (last_day - now).total_seconds()
        if wait <= 0:
            wait = 86400
        print(f"[INFO] Next auto-report: {last_day.strftime('%d.%m.%Y %H:%M')}")
        await asyncio.sleep(wait)
        await send_report_to_all()
        await send_fine_report_to_all()

# ======================================================
# ЗАПУСК
# ======================================================

async def main():
    await init_db()
    await load_employees_from_db()
    print("✅ Bot system started")
    await asyncio.gather(
        worker_dp.start_polling(worker_bot),
        manager_dp.start_polling(manager_bot),
        monthly_scheduler(),
        check_no_shows(),
    )

if __name__ == "__main__":
    asyncio.run(main())