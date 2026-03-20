import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ForceReply
import aiosqlite
from datetime import datetime, timedelta

# -------- TOKENS --------
WORKER_BOT_TOKEN  = "8714366872:AAFmKwU-T2E_JMqDUz_xv23PEko5LeHWfOw"
MANAGER_BOT_TOKEN = "8758406348:AAEjNIPMChEc1gZ3IQlh7aUCShVwutGHOFU"

MANAGER_CHAT_ID = 5952683615
MANAGER_CHAT_ID = 39730332
MANAGER_CHAT_ID = 8473394162

worker_bot  = Bot(token=WORKER_BOT_TOKEN)
manager_bot = Bot(token=MANAGER_BOT_TOKEN)

worker_dp  = Dispatcher()
manager_dp = Dispatcher()

DB         = "attendance.db"
user_state = {}

employees = [
    ("#A770", "Abdulloh", "16:00", "Main: 16:00 - 00:00"),
    ("#L470", "Mubina",   "00:00", "Night: 00:00 - 08:00"),
    ("#D370", "Davlat",   "16:00", "Main: 16:00 - 00:00"),
    ("#D870", "Davron",   "08:00", "Day: 08:00 - 16:00"),
    ("#J660", "Laziz",    "08:00", "Day: 08:00 - 16:00"),
    ("#P710", "Ibrohim",  "00:00", "Night: 00:00 - 08:00"),
    ("#J450", "Yusuf",    "16:00", "Main: 16:00 - 00:00"),
    ("#A777", "Bobur",    "08:00", "Day: 08:00 - 16:00"),
    ("#C333", "Abdulaziz","00:00", "Night: 00:00 - 08:00"),
]

emp_by_fullname = {f"{e[1]} {e[0]}": e for e in employees}
emp_by_id       = {e[0]: e for e in employees}
emp_by_name     = {e[1].lower(): e for e in employees}


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
        )
        """)
        await db.commit()

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

# -------- HELPERS --------
def get_month_key(date):
    return f"{date.year}-M{date.month:02d}"

def format_late(minutes):
    if minutes <= 0: return "✅ On time"
    h, m = minutes // 60, minutes % 60
    if h > 0: return f"⏰ {h}h {m}min late"
    return f"⏰ {m} min late"

def format_total_late(minutes):
    if minutes <= 0: return "0 min"
    h, m = minutes // 60, minutes % 60
    if h > 0 and m > 0: return f"{h}h {m}min"
    elif h > 0: return f"{h}h"
    return f"{m} min"

def get_shift_times(emp, now):
    shift_hour = int(emp[2].split(":")[0])
    if shift_hour == 8:
        start = now.replace(hour=8,  minute=0, second=0, microsecond=0)
        end   = now.replace(hour=16, minute=0, second=0, microsecond=0)
    elif shift_hour == 16:
        start = now.replace(hour=16, minute=0, second=0, microsecond=0)
        end   = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif shift_hour == 0:
        if now.hour >= 20:
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=8)
    else:
        start = end = now
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

        shift_start, shift_end = get_shift_times(emp, now)
        if not (shift_start - timedelta(hours=1) <= now <= shift_end):
            await message.answer(
                f"⛔ Check-in not allowed now!\n"
                f"📋 {emp[1]}'s shift: {emp[3]}\n"
                f"🕐 Starts: {shift_start.strftime('%H:%M')}  Ends: {shift_end.strftime('%H:%M')}")
            return

        late   = calc_late_minutes(shift_start, now)
        week   = get_month_key(now)
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        async with aiosqlite.connect(DB) as db:
            await db.execute(
                "INSERT INTO attendance (employee_id, checkin, late, week) VALUES (?, ?, ?, ?)",
                (emp[0], now.isoformat(), late, week))
            await db.commit()
            cursor = await db.execute(
                "SELECT SUM(late) FROM attendance WHERE employee_id=? AND week=? AND checkin >= ?",
                (emp[0], week, monday.isoformat()))
            row        = await cursor.fetchone()
            total_late = row[0] if row[0] else 0

        weekly_status = "OFF- ❌ (>30 min)" if total_late > 30 else "OFF- ✅"
        late_msg      = format_late(late)
        late_emoji    = "🟢" if late == 0 else "🟡" if late <= 15 else "🔴"

        await message.answer(
            f"✅ {emp[1]} checked in\n"
            f"🕒 Time: {time_str}\n"
            f"📋 Shift: {emp[3]}\n"
            f"⏱ {late_msg}\n"
            f"📊 Total Monthly Late: {format_total_late(total_late)}  {weekly_status}")

        try:
            await manager_bot.send_message(MANAGER_CHAT_ID,
                f"{late_emoji} CHECK-IN\n\n"
                f"👤 {emp[1]} {emp[0]}\n"
                f"🕒 Time: {time_str}\n"
                f"📋 Shift: {emp[3]}\n"
                f"⏰ Late: {late_msg}\n"
                f"📊 Total Monthly Late: {format_total_late(total_late)}  {weekly_status}")
        except Exception as e:
            print(f"[ERROR] Manager notify: {e}")
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
                    eh, em = early_minutes // 60, early_minutes % 60
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

                try:
                    await manager_bot.send_message(MANAGER_CHAT_ID,
                        f"🔴 CHECK-OUT\n\n"
                        f"👤 {emp[1]} {emp[0]}\n"
                        f"🕒 Time: {time_str}\n"
                        f"⏱ Worked: {worked_h}h {worked_m}min{early_msg}")
                except Exception as e:
                    print(f"[ERROR] Manager notify: {e}")
                user_state.pop(uid, None)
            else:
                await message.answer(f"❌ {emp[1]} has no active check-in.", reply_markup=checkout_keyboard())
        return


# ======================================================
# MANAGER BOT
# ======================================================

# Manager bot state
manager_state = {}

def manager_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Report"), KeyboardButton(text="📋 History")],
            [KeyboardButton(text="➕ Add Employee"), KeyboardButton(text="❌ Remove Employee")],
        ],
        resize_keyboard=True
    )

def shift_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌅 Day (08:00-16:00)")],
            [KeyboardButton(text="🌆 Main (16:00-00:00)")],
            [KeyboardButton(text="🌙 Night (00:00-08:00)")],
            [KeyboardButton(text="🔙 Cancel")],
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



@manager_dp.message(CommandStart())
async def manager_start(message: types.Message):
    manager_state.pop(message.from_user.id, None)
    await message.answer(
        "👋 Manager Panel\nSelect action:",
        reply_markup=manager_main_keyboard()
    )

@manager_dp.message(Command("report"))
async def manager_report_cmd(message: types.Message):
    await send_monthly_report(on_demand=True)

@manager_dp.message()
async def manager_handler(message: types.Message):
    text = message.text or ""
    uid  = message.from_user.id
    state = manager_state.get(uid, {})

    # ── CANCEL ────────────────────────────────────────────
    if text == "🔙 Cancel":
        manager_state.pop(uid, None)
        await message.answer("Main menu:", reply_markup=manager_main_keyboard())
        return

    # ── REPORT ────────────────────────────────────────────
    if text == "📊 Report":
        await send_monthly_report(on_demand=True)
        return

    # ── HISTORY — select employee ──────────────────────────
    if text == "📋 History":
        await message.answer("Select employee:", reply_markup=history_employees_keyboard())
        manager_state[uid] = {"mode": "history"}
        return

    if state.get("mode") == "history" and text.startswith("📋 "):
        fullname = text.replace("📋 ", "").strip()
        emp = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❌ Employee not found.")
            return

        now    = datetime.now()
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
                f"   Worked: {wm//60}h {wm%60}min  |  {format_late(late or 0)}")

        lines.append("\n――――――――――――――――――――――――――――――")
        lines.append(f"📊 Total late: {format_total_late(total_late)}")
        lines.append(f"⏱ Total worked: {total_worked//60}h {total_worked%60}min")
        lines.append(f"🏷 Status: {'OFF- ❌' if total_late > 30 else 'OFF- ✅'}")
        await message.answer("\n".join(lines), reply_markup=manager_main_keyboard())
        manager_state.pop(uid, None)
        return

    # ── ADD EMPLOYEE — step 1: ask name ───────────────────
    if text == "➕ Add Employee":
        manager_state[uid] = {"mode": "add", "step": "name"}
        await message.answer(
            "➕ Add new employee\n\nStep 1/3: Enter employee name:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Enter name...")
        )
        return

    if state.get("mode") == "add":
        step = state.get("step")

        # Step 1: got name → ask id
        if step == "name":
            manager_state[uid] = {"mode": "add", "step": "id", "name": text}
            await message.answer(
                f"👤 Name: {text}\n\nStep 2/3: Enter employee ID (e.g. #X123):",
                reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. #X123")
            )
            return

        # Step 2: got id → ask shift
        if step == "id":
            emp_id = text.strip()
            if emp_id in emp_by_id:
                await message.answer(f"❌ ID {emp_id} already exists! Enter a different ID:")
                return
            manager_state[uid] = {**state, "step": "shift", "id": emp_id}
            await message.answer(
                f"👤 Name: {state['name']}\n🆔 ID: {emp_id}\n\n"
                f"Step 3/3: Select shift:",
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text="🌅 Day (08:00-16:00)")],
                        [KeyboardButton(text="🌆 Main (16:00-00:00)")],
                        [KeyboardButton(text="🌙 Night (00:00-08:00)")],
                        [KeyboardButton(text="🔙 Cancel")],
                    ],
                    resize_keyboard=True
                )
            )
            return

        # Step 3: got shift text → save
        if step == "shift":
            shift_map = {
                "🌅 Day (08:00-16:00)":  ("08:00", "Day: 08:00 - 16:00"),
                "🌆 Main (16:00-00:00)": ("16:00", "Main: 16:00 - 00:00"),
                "🌙 Night (00:00-08:00)":("00:00", "Night: 00:00 - 08:00"),
            }
            if text not in shift_map:
                await message.answer("❌ Please select a shift using the buttons.")
                return
            shift, label = shift_map[text]
            name    = state["name"]
            emp_id  = state["id"]
            new_emp = (emp_id, name, shift, label)

            employees.append(new_emp)
            emp_by_fullname[f"{name} {emp_id}"] = new_emp
            emp_by_id[emp_id]                   = new_emp
            emp_by_name[name.lower()]           = new_emp

            manager_state.pop(uid, None)
            await message.answer(
                f"✅ Employee added!\n\n"
                f"👤 {name} {emp_id}\n"
                f"📋 Shift: {label}",
                reply_markup=manager_main_keyboard()
            )
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
        emp = emp_by_fullname.get(fullname)
        if not emp:
            await message.answer("❌ Employee not found.")
            return

        employees.remove(emp)
        emp_by_fullname.pop(f"{emp[1]} {emp[0]}", None)
        emp_by_id.pop(emp[0], None)
        emp_by_name.pop(emp[1].lower(), None)
        manager_state.pop(uid, None)

        await message.answer(
            f"✅ Removed!\n👤 {emp[1]} {emp[0]}",
            reply_markup=manager_main_keyboard()
        )
        return

    # ── FALLBACK ──────────────────────────────────────────
    await message.answer("Select action:", reply_markup=manager_main_keyboard())



# ======================================================
# WEEKLY REPORT
# ======================================================

async def send_monthly_report(on_demand=False):
    now         = datetime.now()
    month       = get_month_key(now)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    label       = " (on demand)" if on_demand else ""

    lines = [f"📊 MONTHLY REPORT{label}",
             f"🗓 Month: {month_start.strftime('%B %Y')}",
             "――――――――――――――――――――――――――――――"]

    async with aiosqlite.connect(DB) as db:
        for emp in employees:
            cursor = await db.execute(
                "SELECT COUNT(*), SUM(late) FROM attendance WHERE employee_id=? AND week=? AND checkin >= ?",
                (emp[0], month, month_start.isoformat()))
            row        = await cursor.fetchone()
            shifts     = row[0] or 0
            total_late = row[1] or 0
            status     = "OFF- ❌" if total_late > 30 else "OFF- ✅"
            late_str   = format_total_late(total_late) if total_late > 0 else "✅ No lates"
            lines.append(
                f"\n👤 {emp[1]} {emp[0]}\n"
                f"   Shifts: {shifts}  |  Total late: {format_total_late(total_late)}\n"
                f"   {late_str}  —  {status}")

    lines.append("\n――――――――――――――――――――――――――――――")
    lines.append(f"📅 {now.strftime('%d.%m.%Y %H:%M')}")

    try:
        await manager_bot.send_message(MANAGER_CHAT_ID, "\n".join(lines))
        print(f"[INFO] Monthly report sent {now.strftime('%d.%m.%Y %H:%M')}")
    except Exception as e:
        print(f"[ERROR] Monthly report: {e}")

# ======================================================
# NO-SHOW CHECKER
# ======================================================

async def check_no_shows():
    """Every minute — alerts manager if employee missed shift start by 30 min"""
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
                    try:
                        await manager_bot.send_message(MANAGER_CHAT_ID,
                            f"🚨 NO-SHOW ALERT\n\n"
                            f"👤 {emp[1]} {emp[0]}\n"
                            f"📋 Shift: {emp[3]}\n"
                            f"🕐 Should have started at {shift_start.strftime('%H:%M')}\n"
                            f"⏰ 30 min passed — not checked in!")
                        print(f"[ALERT] {emp[1]} no-show at {shift_start.strftime('%H:%M')}")
                    except Exception as e:
                        print(f"[ERROR] No-show alert: {e}")

# ======================================================
# WEEKLY SCHEDULER
# ======================================================

async def monthly_report_scheduler():
    while True:
        now        = datetime.now()
        # Last day of current month at 23:59
        if now.month == 12:
            next_month = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = (next_month - timedelta(seconds=1)).replace(hour=23, minute=59, second=0, microsecond=0)
        if last_day <= now:
            last_day = next_month.replace(
                month=next_month.month+1 if next_month.month < 12 else 1,
                year=next_month.year if next_month.month < 12 else next_month.year+1,
                day=1
            ) - timedelta(days=1)
            last_day = last_day.replace(hour=23, minute=59, second=0, microsecond=0)
        wait = (last_day - now).total_seconds()
        print(f"[INFO] Next monthly report: {last_day.strftime('%d.%m.%Y %H:%M')} (in {int(wait//3600)}h {int((wait%3600)//60)}m)")
        await asyncio.sleep(wait)
        await send_monthly_report()

# ======================================================
# RUN
# ======================================================

async def main():
    await init_db()
    print("✅ System started")
    await asyncio.gather(
        worker_dp.start_polling(worker_bot),
        manager_dp.start_polling(manager_bot),
        monthly_report_scheduler(),
        check_no_shows(),
    )

if __name__ == "__main__":
    asyncio.run(main())