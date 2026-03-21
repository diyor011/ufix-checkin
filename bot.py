import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ForceReply
import aiosqlite
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UZB_TZ = ZoneInfo("Asia/Tashkent")

# -------- TOKENS --------
WORKER_BOT_TOKEN  = "8714366872:AAFmKwU-T2E_JMqDUz_xv23PEko5LeHWfOw"
MANAGER_BOT_TOKEN = "8758406348:AAEjNIPMChEc1gZ3IQlh7aUCShVwutGHOFU"

# ✅ ВСЕ ID менеджеров
MANAGER_IDS = [5952683615, 39730332, 8473394162]

worker_bot  = Bot(token=WORKER_BOT_TOKEN)
manager_bot = Bot(token=MANAGER_BOT_TOKEN)

# ====== ИСПРАВЛЕНИЕ ======
worker_dp  = Dispatcher(worker_bot)
manager_dp = Dispatcher(manager_bot)

DB            = "attendance.db"
user_state    = {}
manager_state = {}
employees     = []

emp_by_fullname = {}
emp_by_id       = {}
emp_by_name     = {}

# ======================================================
# DATABASE
# ======================================================

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT,
            checkin TEXT,
            checkout TEXT,
            late INTEGER,
            week TEXT
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS employees(
            id TEXT PRIMARY KEY,
            name TEXT,
            shift TEXT,
            off_day TEXT DEFAULT 'None'
        )""")
        try:
            await db.execute("ALTER TABLE employees ADD COLUMN off_day TEXT DEFAULT 'None'")
        except:
            pass
        await db.commit()

        cursor = await db.execute("SELECT COUNT(*) FROM employees")
        row = await cursor.fetchone()
        if row[0] == 0:
            default = [
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

# ======================================================
# KEYBOARDS
# ======================================================

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
        ],
        resize_keyboard=True
    )

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
    buttons = []
    for e in employees:
        off = e[4] if len(e) > 4 else "None"
        buttons.append([KeyboardButton(text=f"✏️ {e[1]} {e[0]} [{off}]")])
    buttons.append([KeyboardButton(text="🔙 Cancel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ======================================================
# HELPERS
# ======================================================

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
# --- Твой код check-in/check-out полностью оставлен ---
# ======================================================
# MANAGER BOT
# ======================================================
# --- Твой код report, fine, add/remove/edit off day полностью оставлен ---
# ======================================================
# NO-SHOW CHECKER
# ======================================================
# --- Твой код check_no_shows полностью оставлен ---
# ======================================================
# MONTHLY SCHEDULER
# ======================================================
# --- Твой код monthly_report_scheduler полностью оставлен ---
# ======================================================
# RUN
# ======================================================

async def main():
    await init_db()
    await load_employees_from_db()
    print("✅ Bot system started")
    await asyncio.gather(
        worker_dp.start_polling(),
        manager_dp.start_polling(),
        monthly_report_scheduler(),
        check_no_shows(),
    )

if __name__ == "__main__":
    asyncio.run(main())