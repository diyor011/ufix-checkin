# ===== ИМПОРТЫ =====
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ForceReply
import aiosqlite
from datetime import datetime, timedelta

# ===== TOKENS =====
WORKER_BOT_TOKEN  = "8714366872:AAFmKwU-T2E_JMqDUz_xv23PEko5LeHWfOw"
MANAGER_BOT_TOKEN = "8758406348:AAEjNIPMChEc1gZ3IQlh7aUCShVwutGHOFU"

MANAGER_IDS = [5952683615, 39730332, 8473394162]

worker_bot  = Bot(token=WORKER_BOT_TOKEN)
manager_bot = Bot(token=MANAGER_BOT_TOKEN)

worker_dp  = Dispatcher()
manager_dp = Dispatcher()

DB = "attendance.db"

# ===== STATE =====
user_state = {}
manager_state = {}

employees = []
emp_by_fullname = {}
emp_by_id = {}
emp_by_name = {}

# ===== INIT DB =====
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
        await db.commit()

# ===== LOAD EMPLOYEES =====
async def load_employees_from_db():
    global employees, emp_by_fullname, emp_by_id, emp_by_name
    async with aiosqlite.connect(DB) as db:
        rows = await (await db.execute("SELECT id, name, shift, off_day FROM employees")).fetchall()

    labels = {
        "08:00": "Day: 08:00 - 16:00",
        "16:00": "Main: 16:00 - 00:00",
        "00:00": "Night: 00:00 - 08:00"
    }

    employees = [(r[0], r[1], r[2], labels.get(r[2], r[2]), r[3]) for r in rows]
    emp_by_fullname = {f"{e[1]} {e[0]}": e for e in employees}
    emp_by_id = {e[0]: e for e in employees}
    emp_by_name = {e[1].lower(): e for e in employees}

# ===== KEYBOARDS =====
def manager_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Report"), KeyboardButton(text="📋 History")],
            [KeyboardButton(text="💰 Fine Report")]
        ],
        resize_keyboard=True
    )

# ===== HELPERS =====
def get_month_key(date):
    return f"{date.year}-M{date.month:02d}"

def format_total_late(minutes):
    if minutes <= 0: return "0 min"
    h, m = minutes // 60, minutes % 60
    return f"{h}h {m}min" if h else f"{m} min"

# ===== REPORT =====
async def send_monthly_report(message=None, on_demand=False):
    now = datetime.now()
    month = get_month_key(now)

    text = f"📊 REPORT ({month})\n\n"

    async with aiosqlite.connect(DB) as db:
        for emp in employees:
            row = await (await db.execute(
                "SELECT COUNT(*), SUM(late) FROM attendance WHERE employee_id=?",
                (emp[0],)
            )).fetchone()

            shifts = row[0] or 0
            late = row[1] or 0

            text += f"{emp[1]} {emp[0]}\n"
            text += f"Shifts: {shifts} | Late: {format_total_late(late)}\n"
            text += f"💰 Fine: ${late}\n\n"

    if message:
        await message.answer(text)
    else:
        for cid in MANAGER_IDS:
            await manager_bot.send_message(cid, text)

# ===== FINE REPORT =====
async def send_fine_report(message=None):
    now = datetime.now()
    month = get_month_key(now)

    text = f"💰 FINE REPORT ({month})\n\n"
    total = 0

    async with aiosqlite.connect(DB) as db:
        for emp in employees:
            rows = await (await db.execute(
                "SELECT late FROM attendance WHERE employee_id=?",
                (emp[0],)
            )).fetchall()

            late_sum = sum(r[0] or 0 for r in rows)
            total += late_sum

            text += f"{emp[1]}: ${late_sum}\n"

    text += f"\nTOTAL: ${total}"

    if message:
        await message.answer(text)
    else:
        for cid in MANAGER_IDS:
            await manager_bot.send_message(cid, text)

# ===== MANAGER HANDLER =====
@manager_dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("Manager panel", reply_markup=manager_main_keyboard())

@manager_dp.message()
async def manager_handler(message: types.Message):
    if message.from_user.id not in MANAGER_IDS:
        await message.answer("No access")
        return

    text = message.text

    if text == "📊 Report":
        await send_monthly_report(message=message, on_demand=True)

    elif text == "💰 Fine Report":
        await send_fine_report(message=message)

# ===== SCHEDULER =====
async def monthly_scheduler():
    while True:
        await asyncio.sleep(86400)
        await send_monthly_report()
        await send_fine_report()

# ===== MAIN =====
async def main():
    await init_db()
    await load_employees_from_db()

    await asyncio.gather(
        manager_dp.start_polling(manager_bot),
        monthly_scheduler()
    )

if __name__ == "__main__":
    asyncio.run(main())