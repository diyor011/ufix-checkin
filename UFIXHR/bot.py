import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ForceReply
import aiosqlite
from datetime import datetime, timedelta

# -------- TOKENS --------
WORKER_BOT_TOKEN  = "8714366872:AAFmKwU-T2E_JMqDUz_xv23PEko5LeHWfOw"
MANAGER_BOT_TOKEN = "8758406348:AAEjNIPMChEc1gZ3IQlh7aUCShVwutGHOFU"

# ✅ ВСЕ ID менеджеров
MANAGER_IDS = [5952683615, 39730332, 8473394162]

worker_bot  = Bot(token=WORKER_BOT_TOKEN)
manager_bot = Bot(token=MANAGER_BOT_TOKEN)

worker_dp  = Dispatcher()
manager_dp = Dispatcher()

async def notify_managers(text=None, photo=None, caption=None):
    for cid in MANAGER_IDS:
        try:
            if photo:
                await manager_bot.send_photo(cid, photo, caption=caption)
            else:
                await manager_bot.send_message(cid, text)
        except Exception as e:
            print(f"[ERROR] notify {cid}: {e}")

DB         = "attendance.db"
user_state = {}

employees = []

emp_by_fullname = {}
emp_by_id       = {}
emp_by_name     = {}

# -------- DATABASE --------
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT,
            checkin TEXT,
            checkout TEXT,
            late INTEGER,
            week TEXT
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS employees(
            id TEXT PRIMARY KEY,
            name TEXT,
            shift TEXT,
            off_day TEXT DEFAULT 'None'
        )""")
        try:
            await db.execute("ALTER TABLE employees ADD COLUMN off_day TEXT DEFAULT 'None'")
            await db.commit()
        except:
            pass
        cursor = await db.execute("SELECT COUNT(*) FROM employees")
        row = await cursor.fetchone()
        if row[0] == 0:
            default = [
                ("#A770", "Abdulloh", "16:00", "None"),
                ("#L470", "Mubina",   "00:00", "None"),
                ("#D370", "Davlat",   "16:00", "None"),
                ("#D870", "Davron",   "08:00", "None"),
                ("#J660", "Laziz",    "08:00", "None"),
                ("#P710", "Ibrohim",  "00:00", "None"),
                ("#J450", "Yusuf",    "16:00", "None"),
                ("#A777", "Bobur",    "08:00", "None"),
                ("#C333", "Abdulaziz","00:00", "None"),
            ]
            for e in default:
                await db.execute("INSERT OR IGNORE INTO employees VALUES (?,?,?,?)", e)
        await db.commit()

async def load_employees_from_db():
    global employees, emp_by_fullname, emp_by_id, emp_by_name
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute("SELECT id, name, shift, off_day FROM employees")
        rows = await cursor.fetchall()
    if rows:
        labels = {
            "08:00": "Day: 08:00 - 16:00",
            "16:00": "Main: 16:00 - 00:00",
            "00:00": "Night: 00:00 - 08:00"
        }
        employees       = [(r[0], r[1], r[2], labels.get(r[2], r[2]), r[3] or "None") for r in rows]
        emp_by_fullname = {f"{e[1]} {e[0]}": e for e in employees}
        emp_by_id       = {e[0]: e for e in employees}
        emp_by_name     = {e[1].lower(): e for e in employees}

# -------- KEYBOARDS --------
def employees_keyboard():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"{e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Check-in"), KeyboardButton(text="📤 Check-out")],
            [KeyboardButton(text="⬅️ Back")]
        ], resize_keyboard=True)

def checkout_keyboard():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"📤 {e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([KeyboardButton(text="⬅️ Back")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def manager_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Report"),        KeyboardButton(text="📋 History")],
            [KeyboardButton(text="💰 Fine Report"),   KeyboardButton(text="✏️ Edit Off Day")],
            [KeyboardButton(text="➕ Add Employee"),  KeyboardButton(text="❌ Remove Employee")],
        ],
        resize_keyboard=True
    )

def remove_employees_keyboard():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"🗑 {e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([KeyboardButton(text="🔙 Cancel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def history_employees_keyboard():
    buttons, row = [], []
    for e in employees:
        row.append(KeyboardButton(text=f"📋 {e[1]} {e[0]}"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([KeyboardButton(text="🔙 Cancel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def edit_offday_employees_keyboard():
    buttons, row = [], []
    for e in employees:
        off   = e[4] if len(e) > 4 else "None"
        label = f"✏️ {e[1]} {e[0]} [{off}]"
        row.append(KeyboardButton(text=label))
        if len(row) == 1:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([KeyboardButton(text="🔙 Cancel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# -------- HELPERS --------
def get_month_key(date):
    return f"{date.year}-M{date.month:02d}"

def format_late(minutes):
    if minutes <= 0: return "✅ On time"
    h, m = minutes // 60, minutes % 60
    return f"⏰ {h}h {m}min late" if h > 0 else f"⏰ {m} min late"

def format_total_late(minutes):
    if minutes <= 0: return "0 min"
    h, m = minutes // 60, minutes % 60
    if h > 0 and m > 0: return f"{h}h {m}min"
    return f"{h}h" if h > 0 else f"{m} min"

def get_shift_times(emp, now):
    shift_hour = int(emp[2].split(":")[0])
    if shift_hour == 8:
        start = now.replace(hour=8,  minute=0, second=0, microsecond=0)
        end   = now.replace(hour=16, minute=0, second=0, microsecond=0)
    elif shift_hour == 16:
        start = now.replace(hour=16, minute=0, second=0, microsecond=0)
        end   = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        if now.hour >= 20:
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=8)
    return start, end

def calc_late_minutes(shift_start, now):
    return max(int((now - shift_start).total_seconds() / 60), 0)


# ======================================================
# WORKER BOT
# ======================================================

@worker_dp.message(CommandStart())
async def worker_start(message: types.Message):
    user_state.pop(message.from_user.id, None)
    await message.answer("👋 Attendance System\n\nSelect employee:", reply_markup=employees_keyboard())

@worker_dp.message()
async def worker_handler(message: types.Message):
    text  = message.text or ""
    uid   = message.from_user.id
    state = user_state.get(uid, {})

    if text == "⬅️ Back":
        user_state.pop(uid, None)
        await message.answer("Select employee:", reply_markup=employees_keyboard())
        return

    emp = emp_by_fullname.get(text)
    if emp:
        user_state[uid] = {"emp": emp}
        await message.answer(f"👤 {emp[1]} {emp[0]}\n🕐 Shift: {emp[3]}", reply_markup=main_menu_keyboard())
        return

    if text == "✅ Check-in":
        emp = state.get("emp")
        if not emp:
            await message.answer("❗ Please select an employee first.", reply_markup=employees_keyboard())
            return

        now      = datetime.now()
        time_str = now.strftime("%H:%M")

        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT id FROM attendance WHERE employee_id=? AND checkout IS NULL ORDER BY id DESC LIMIT 1",
                (emp[0],))
            existing = await cursor.fetchone()

        if existing:
            await message.answer(f"⚠️ {emp[1]} is already checked in! Please check out first.")
            return

        off_day    = emp[4] if len(emp) > 4 else "None"
        today_name = now.strftime("%A")
        if off_day not in ("None", "No day off") and off_day == today_name:
            await message.answer(f"🌴 {emp[1]} has a day off today ({today_name})!\nCheck-in not allowed.")
            return

        shift_start, shift_end = get_shift_times(emp, now)
        if not (shift_start - timedelta(hours=1) <= now <= shift_end):
            await message.answer(
                f"⛔ Check-in not allowed now!\n"
                f"📋 {emp[1]}'s shift: {emp[3]}\n"
                f"🕐 Starts: {shift_start.strftime('%H:%M')}  Ends: {shift_end.strftime('%H:%M')}")
            return

        late        = calc_late_minutes(shift_start, now)
        week        = get_month_key(now)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        async with aiosqlite.connect(DB) as db:
            await db.execute(
                "INSERT INTO attendance (employee_id, checkin, late, week) VALUES (?,?,?,?)",
                (emp[0], now.isoformat(), late, week))
            await db.commit()
            cursor = await db.execute(
                "SELECT SUM(late) FROM attendance WHERE employee_id=? AND week=? AND checkin >= ?",
                (emp[0], week, month_start.isoformat()))
            row2               = await cursor.fetchone()
            total_monthly_late = row2[0] if row2[0] else 0

        late_msg   = format_late(late)
        late_emoji = "🟢" if late <= 15 else "🟡" if late <= 30 else "🔴"
        fine_today = late
        total_fine = total_monthly_late

        await message.answer(
            f"✅ {emp[1]} checked in\n"
            f"🕒 Time: {time_str}\n"
            f"📋 Shift: {emp[3]}\n"
            f"⏱ {late_msg}\n"
            f"💸 Fine today: ${fine_today}\n"
            f"📊 Total Monthly Late: {format_total_late(total_monthly_late)}\n"
            f"💰 Total Monthly Fine: ${total_fine}")

        for _cid in MANAGER_IDS:
            try:
                await manager_bot.send_message(_cid,
                    f"{late_emoji} CHECK-IN\n\n"
                    f"👤 {emp[1]} {emp[0]}\n"
                    f"🕒 Time: {time_str}\n"
                    f"📋 Shift: {emp[3]}\n"
                    f"⏰ {late_msg}\n"
                    f"💸 Fine today: ${fine_today}\n"
                    f"📊 Total Monthly Late: {format_total_late(total_monthly_late)}\n"
                    f"💰 Total Monthly Fine: ${total_fine}")
            except Exception as e:
                print(f"[ERROR] Manager notify {_cid}: {e}")
        return

    if text == "📤 Check-out":
        user_state[uid] = {**state, "mode": "checkout"}
        await message.answer("Select employee to check out:", reply_markup=checkout_keyboard())
        return

    if text.startswith("📤 "):
        fullname = text.replace("📤 ", "").strip()
        emp      = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❗ Employee not found.")
            return

        now      = datetime.now()
        time_str = now.strftime("%H:%M")

        shift_start, shift_end = get_shift_times(emp, now)
        if not (shift_start <= now <= shift_end + timedelta(minutes=30)):
            await message.answer(
                f"⛔ Check-out not allowed now!\n"
                f"📋 {emp[1]}'s shift: {emp[3]}\n"
                f"🕐 Starts: {shift_start.strftime('%H:%M')}  Ends: {shift_end.strftime('%H:%M')}")
            return

        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT id, checkin FROM attendance WHERE employee_id=? AND checkout IS NULL ORDER BY id DESC LIMIT 1",
                (emp[0],))
            row = await cursor.fetchone()

            if row:
                record_id, checkin_str = row
                checkin_dt     = datetime.fromisoformat(checkin_str)
                worked_minutes = int((now - checkin_dt).total_seconds() / 60)
                worked_h, worked_m = worked_minutes // 60, worked_minutes % 60
                early_minutes  = int((shift_end - now).total_seconds() / 60) if now < shift_end else 0
                if early_minutes >= 60:
                    eh, em    = early_minutes // 60, early_minutes % 60
                    early_msg = f"\n⚠️ Left {eh}h {em}min early!" if em > 0 else f"\n⚠️ Left {eh}h early!"
                elif early_minutes > 0:
                    early_msg = f"\n⚠️ Left {early_minutes} min early!"
                else:
                    early_msg = ""

                await db.execute("UPDATE attendance SET checkout=? WHERE id=?", (now.isoformat(), record_id))
                await db.commit()

                await message.answer(
                    f"📤 {emp[1]} checked out\n"
                    f"🕒 Time: {time_str}\n"
                    f"⏱ Worked: {worked_h}h {worked_m}min{early_msg}",
                    reply_markup=employees_keyboard())

                for _cid in MANAGER_IDS:
                    try:
                        await manager_bot.send_message(_cid,
                            f"🔴 CHECK-OUT\n\n"
                            f"👤 {emp[1]} {emp[0]}\n"
                            f"🕒 Time: {time_str}\n"
                            f"⏱ Worked: {worked_h}h {worked_m}min{early_msg}")
                    except Exception as e:
                        print(f"[ERROR] Manager notify {_cid}: {e}")
                user_state.pop(uid, None)
            else:
                await message.answer(f"❌ {emp[1]} has no active check-in.", reply_markup=checkout_keyboard())
        return


# ======================================================
# MANAGER BOT
# ======================================================

manager_state = {}

@manager_dp.message(CommandStart())
async def manager_start(message: types.Message):
    manager_state.pop(message.from_user.id, None)
    await message.answer("👋 Manager Panel\nSelect action:", reply_markup=manager_main_keyboard())

@manager_dp.message(Command("report"))
async def manager_report_cmd(message: types.Message):
    await send_monthly_report(message=message, on_demand=True)

@manager_dp.message()
async def manager_handler(message: types.Message):
    text  = message.text or ""
    uid   = message.from_user.id
    state = manager_state.get(uid, {})

    # ── CANCEL ────────────────────────────────────────────
    if text == "🔙 Cancel":
        manager_state.pop(uid, None)
        await message.answer("Main menu:", reply_markup=manager_main_keyboard())
        return

    # ── REPORT ✅ ИСПРАВЛЕНО ──────────────────────────────
    if text == "📊 Report":
        await send_monthly_report(message=message, on_demand=True)
        return

    # ── FINE REPORT ───────────────────────────────────────
    if text == "💰 Fine Report":
        await send_fine_report(message=message)
        return

    # ── HISTORY ───────────────────────────────────────────
    if text == "📋 History":
        await message.answer("Select employee:", reply_markup=history_employees_keyboard())
        manager_state[uid] = {"mode": "history"}
        return

    if state.get("mode") == "history" and text.startswith("📋 "):
        fullname = text.replace("📋 ", "").strip()
        emp      = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❌ Employee not found.")
            return

        now         = datetime.now()
        month       = get_month_key(now)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        async with aiosqlite.connect(DB) as db:
            cursor = await db.execute(
                "SELECT checkin, checkout, late FROM attendance WHERE employee_id=? AND week=? AND checkin >= ? ORDER BY checkin ASC",
                (emp[0], month, month_start.isoformat()))
            rows = await cursor.fetchall()

        if not rows:
            await message.answer(f"📭 No records for {emp[1]} this month.", reply_markup=manager_main_keyboard())
            manager_state.pop(uid, None)
            return

        lines        = [f"📋 {emp[1]} {emp[0]}", f"🗓 Month: {month_start.strftime('%B %Y')}", "――――――――――――――――――――――――――――――"]
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
                f"   In: {ci.strftime('%H:%M')}  Out: {co.strftime('%H:%M') if co else 'active'}\n"
                f"   Worked: {wm//60}h {wm%60}min  |  {format_late(late or 0)}\n"
                f"   💸 Fine: ${late or 0}")

        lines.append("\n――――――――――――――――――――――――――――――")
        lines.append(f"📊 Total late: {format_total_late(total_late)}")
        lines.append(f"💰 Total fine: ${total_late}")
        lines.append(f"⏱ Total worked: {total_worked//60}h {total_worked%60}min")
        await message.answer("\n".join(lines), reply_markup=manager_main_keyboard())
        manager_state.pop(uid, None)
        return

    # ── ADD EMPLOYEE ──────────────────────────────────────
    if text == "➕ Add Employee":
        manager_state[uid] = {"mode": "add", "step": "name"}
        await message.answer(
            "➕ Add new employee\n\nStep 1/4: Enter employee name:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Enter name...")
        )
        return

    if state.get("mode") == "add":
        step = state.get("step")

        if step == "name":
            manager_state[uid] = {"mode": "add", "step": "id", "name": text}
            await message.answer(
                f"👤 Name: {text}\n\nStep 2/4: Enter employee ID (e.g. #X123):",
                reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. #X123")
            )
            return

        if step == "id":
            emp_id = text.strip()
            if emp_id in emp_by_id:
                await message.answer(f"❌ ID {emp_id} already exists! Enter a different ID:")
                return
            manager_state[uid] = {**state, "step": "shift", "id": emp_id}
            await message.answer(
                f"👤 Name: {state['name']}\n🆔 ID: {emp_id}\n\nStep 3/4: Select shift:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="🌅 Day (08:00-16:00)")],
                        [KeyboardButton(text="🌆 Main (16:00-00:00)")],
                        [KeyboardButton(text="🌙 Night (00:00-08:00)")],
                        [KeyboardButton(text="🔙 Cancel")],
                    ], resize_keyboard=True))
            return

        if step == "shift":
            shift_map = {
                "🌅 Day (08:00-16:00)":   ("08:00", "Day: 08:00 - 16:00"),
                "🌆 Main (16:00-00:00)":  ("16:00", "Main: 16:00 - 00:00"),
                "🌙 Night (00:00-08:00)": ("00:00", "Night: 00:00 - 08:00"),
            }
            if text not in shift_map:
                await message.answer("❌ Please select a shift using the buttons.")
                return
            shift, label = shift_map[text]
            manager_state[uid] = {**state, "step": "offday", "shift": shift, "label": label}
            await message.answer(
                f"👤 Name: {state['name']}\n🆔 ID: {state['id']}\n📋 Shift: {label}\n\nStep 4/4: Select off day:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="Monday"),    KeyboardButton(text="Tuesday")],
                        [KeyboardButton(text="Wednesday"), KeyboardButton(text="Thursday")],
                        [KeyboardButton(text="Friday"),    KeyboardButton(text="Saturday")],
                        [KeyboardButton(text="Sunday"),    KeyboardButton(text="No day off")],
                        [KeyboardButton(text="🔙 Cancel")],
                    ], resize_keyboard=True))
            return

        if step == "offday":
            days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","No day off"]
            if text not in days:
                await message.answer("❌ Please select a day using the buttons.")
                return
            off_day = text
            shift   = state["shift"]
            label   = state["label"]
            name    = state["name"]
            emp_id  = state["id"]
            new_emp = (emp_id, name, shift, label, off_day)
            employees.append(new_emp)
            emp_by_fullname[f"{name} {emp_id}"] = new_emp
            emp_by_id[emp_id]                   = new_emp
            emp_by_name[name.lower()]            = new_emp
            async with aiosqlite.connect(DB) as db:
                await db.execute("INSERT OR REPLACE INTO employees VALUES (?,?,?,?)", (emp_id, name, shift, off_day))
                await db.commit()
            manager_state.pop(uid, None)
            await message.answer(
                f"✅ Employee added!\n\n👤 {name} {emp_id}\n📋 Shift: {label}\n🗓 Off day: {off_day}",
                reply_markup=manager_main_keyboard())
            return

    # ── REMOVE EMPLOYEE ───────────────────────────────────
    if text == "❌ Remove Employee":
        if not employees:
            await message.answer("No employees to remove.")
            return
        manager_state[uid] = {"mode": "remove"}
        await message.answer("Select employee to remove:", reply_markup=remove_employees_keyboard())
        return

    if state.get("mode") == "remove" and text.startswith("🗑 "):
        fullname = text.replace("🗑 ", "").strip()
        emp      = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❌ Employee not found.")
            return
        employees.remove(emp)
        emp_by_fullname.pop(f"{emp[1]} {emp[0]}", None)
        emp_by_id.pop(emp[0], None)
        emp_by_name.pop(emp[1].lower(), None)
        async with aiosqlite.connect(DB) as db:
            await db.execute("DELETE FROM employees WHERE id=?", (emp[0],))
            await db.commit()
        manager_state.pop(uid, None)
        await message.answer(f"✅ Removed!\n👤 {emp[1]} {emp[0]}", reply_markup=manager_main_keyboard())
        return

    # ── EDIT OFF DAY ──────────────────────────────────────
    if text == "✏️ Edit Off Day":
        manager_state[uid] = {"mode": "edit_offday"}
        await message.answer("Select employee to edit off day:", reply_markup=edit_offday_employees_keyboard())
        return

    if state.get("mode") == "edit_offday" and text.startswith("✏️ "):
        raw      = text.replace("✏️ ", "").strip()
        bracket  = raw.rfind("[")
        fullname = raw[:bracket].strip() if bracket != -1 else raw
        emp      = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❌ Employee not found.")
            return
        manager_state[uid] = {"mode": "edit_offday_select", "emp": emp}
        await message.answer(
            f"👤 {emp[1]} {emp[0]}\nSelect new off day:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Monday"),    KeyboardButton(text="Tuesday")],
                    [KeyboardButton(text="Wednesday"), KeyboardButton(text="Thursday")],
                    [KeyboardButton(text="Friday"),    KeyboardButton(text="Saturday")],
                    [KeyboardButton(text="Sunday"),    KeyboardButton(text="No day off")],
                    [KeyboardButton(text="🔙 Cancel")],
                ], resize_keyboard=True))
        return

    if state.get("mode") == "edit_offday_select":
        days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","No day off"]
        if text not in days:
            await message.answer("❌ Please select a day using the buttons.")
            return
        emp     = state["emp"]
        off_day = text
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE employees SET off_day=? WHERE id=?", (off_day, emp[0]))
            await db.commit()
        await load_employees_from_db()
        manager_state.pop(uid, None)
        await message.answer(
            f"✅ Off day updated!\n👤 {emp[1]} {emp[0]}\n🗓 New off day: {off_day}",
            reply_markup=manager_main_keyboard())
        return

    # ── FALLBACK ──────────────────────────────────────────
    await message.answer("Select action:", reply_markup=manager_main_keyboard())


# ======================================================
# MONTHLY REPORT ✅ ИСПРАВЛЕНО — принимает message
# ======================================================

async def send_monthly_report(message=None, on_demand=False):
    now         = datetime.now()
    month       = get_month_key(now)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    label       = " (on demand)" if on_demand else ""

    lines = [
        f"📊 MONTHLY REPORT{label}",
        f"🗓 Month: {month_start.strftime('%B %Y')}",
        "――――――――――――――――――――――――――――――"
    ]

    async with aiosqlite.connect(DB) as db:
        for emp in employees:
            cursor = await db.execute(
                "SELECT COUNT(*), SUM(late) FROM attendance WHERE employee_id=? AND week=? AND checkin >= ?",
                (emp[0], month, month_start.isoformat()))
            row        = await cursor.fetchone()
            shifts     = row[0] or 0
            total_late = row[1] or 0
            total_fine = total_late

            lines.append(
                f"\n👤 {emp[1]} {emp[0]}\n"
                f"   Shifts: {shifts}  |  Total late: {format_total_late(total_late)}\n"
                f"   💰 Fine: ${total_fine}")

            cursor2 = await db.execute(
                "SELECT checkin, late FROM attendance WHERE employee_id=? AND week=? AND checkin >= ? AND late > 0 ORDER BY checkin ASC",
                (emp[0], month, month_start.isoformat()))
            day_rows = await cursor2.fetchall()
            if day_rows:
                lines.append("   ── Late days ──")
                for checkin_str, late in day_rows:
                    ci = datetime.fromisoformat(checkin_str)
                    lines.append(
                        f"   📅 {ci.strftime('%a %d.%m')}  "
                        f"In: {ci.strftime('%H:%M')}  "
                        f"Late: {late} min  💸 ${late}")

    lines.append("\n――――――――――――――――――――――――――――――")
    lines.append(f"📅 {now.strftime('%d.%m.%Y %H:%M')}")
    text_out = "\n".join(lines)

    # ✅ Если вызвано из кнопки — отвечаем в чат
    if message:
        await message.answer(text_out, reply_markup=manager_main_keyboard())
    else:
        for _cid in MANAGER_IDS:
            try:
                await manager_bot.send_message(_cid, text_out)
            except Exception as e:
                print(f"[ERROR] Monthly report {_cid}: {e}")

    print(f"[INFO] Monthly report sent {now.strftime('%d.%m.%Y %H:%M')}")


# ======================================================
# FINE REPORT ✅ ИСПРАВЛЕНО — принимает message
# ======================================================

async def send_fine_report(message=None):
    now         = datetime.now()
    month       = get_month_key(now)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    lines = [
        "💰 FINE REPORT",
        f"🗓 Month: {month_start.strftime('%B %Y')}",
        "――――――――――――――――――――――――――――――"
    ]
    total_all = 0

    async with aiosqlite.connect(DB) as db:
        for emp in employees:
            cursor = await db.execute(
                "SELECT checkin, late FROM attendance WHERE employee_id=? AND week=? AND checkin >= ? ORDER BY checkin ASC",
                (emp[0], month, month_start.isoformat()))
            rows       = await cursor.fetchall()
            total_late = sum(r[1] or 0 for r in rows)
            total_all += total_late

            if total_late == 0:
                lines.append(f"\n👤 {emp[1]} {emp[0]}\n   ✅ No fines")
                continue

            lines.append(f"\n👤 {emp[1]} {emp[0]}")
            lines.append(f"   Total late: {format_total_late(total_late)}  |  💰 Fine: ${total_late}")
            lines.append("   ── Daily breakdown ──")
            for checkin_str, late in rows:
                if (late or 0) == 0: continue
                ci = datetime.fromisoformat(checkin_str)
                lines.append(
                    f"   📅 {ci.strftime('%a %d.%m')}  "
                    f"In: {ci.strftime('%H:%M')}  "
                    f"Late: {late} min  💸 ${late}")

    lines.append("\n――――――――――――――――――――――――――――――")
    lines.append(f"💰 TOTAL ALL FINES: ${total_all}")
    lines.append(f"📅 {now.strftime('%d.%m.%Y %H:%M')}")
    text_out = "\n".join(lines)

    if message:
        await message.answer(text_out, reply_markup=manager_main_keyboard())
    else:
        for _cid in MANAGER_IDS:
            try:
                await manager_bot.send_message(_cid, text_out)
            except Exception as e:
                print(f"[ERROR] Fine report {_cid}: {e}")


# ======================================================
# NO-SHOW CHECKER
# ======================================================

async def check_no_shows():
    alerted = set()
    while True:
        await asyncio.sleep(60)
        now = datetime.now()
        async with aiosqlite.connect(DB) as db:
            for emp in employees:
                shift_start, _ = get_shift_times(emp, now)
                alert_time     = shift_start + timedelta(minutes=30)
                alert_key      = f"{emp[0]}-{shift_start.isoformat()}"
                if not (alert_time <= now <= alert_time + timedelta(minutes=1)):
                    continue
                if alert_key in alerted:
                    continue
                cursor = await db.execute(
                    "SELECT id FROM attendance WHERE employee_id=? AND checkin >= ?",
                    (emp[0], shift_start.isoformat()))
                row = await cursor.fetchone()
                if not row:
                    alerted.add(alert_key)
                    for _cid in MANAGER_IDS:
                        try:
                            await manager_bot.send_message(_cid,
                                f"🚨 NO-SHOW ALERT\n\n"
                                f"👤 {emp[1]} {emp[0]}\n"
                                f"📋 Shift: {emp[3]}\n"
                                f"🕐 Should have started at {shift_start.strftime('%H:%M')}\n"
                                f"⏰ 30 min passed — not checked in!")
                        except Exception as e:
                            print(f"[ERROR] No-show {_cid}: {e}")


# ======================================================
# MONTHLY SCHEDULER
# ======================================================

async def monthly_report_scheduler():
    while True:
        now = datetime.now()
        if now.month == 12:
            next_month = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = (next_month - timedelta(seconds=1)).replace(hour=23, minute=59, second=0, microsecond=0)
        wait = (last_day - now).total_seconds()
        if wait <= 0:
            wait = 86400
        print(f"[INFO] Next monthly report: {last_day.strftime('%d.%m.%Y %H:%M')}")
        await asyncio.sleep(wait)
        await send_monthly_report()
        await send_fine_report()


# ======================================================
# RUN
# ======================================================

async def main():
    await init_db()
    await load_employees_from_db()
    print("✅ Bot system started")
    await asyncio.gather(
        worker_dp.start_polling(worker_bot),
        manager_dp.start_polling(manager_bot),
        monthly_report_scheduler(),
        check_no_shows(),
    )

if __name__ == "__main__":
    asyncio.run(main())