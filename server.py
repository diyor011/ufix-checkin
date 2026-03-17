from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3, requests, os, threading, time, asyncio
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Путь к БД — всегда рядом с этим файлом
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "attendance.db")

DEFAULT_EMPLOYEES = [
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

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT,
            checkin TEXT,
            checkout TEXT,
            late INTEGER,
            week TEXT
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS employees(
            id TEXT PRIMARY KEY,
            name TEXT,
            shift TEXT,
            off_day TEXT DEFAULT 'None'
        )""")
    try:
        conn.execute("ALTER TABLE employees ADD COLUMN off_day TEXT DEFAULT 'None'")
    except:
        pass
    count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if count == 0:
        for e in DEFAULT_EMPLOYEES:
            conn.execute("INSERT OR IGNORE INTO employees VALUES (?,?,?,?)", e)
    conn.commit()
    conn.close()
    print(f"[DB] Ready: {DB}")

init_db()

# ── Telegram ─────────────────────────────────────────────
BOT_TOKEN    = "8758406348:AAEjNIPMChEc1gZ3IQlh7aUCShVwutGHOFU"
MANAGER_IDS  = ["5952683615", "39730332"]

def tg_send(text):
    for cid in MANAGER_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": text}, timeout=5)
        except Exception as e:
            print(f"[TG ERROR] {e}")

def tg_photo(photo_bytes, caption):
    for cid in MANAGER_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": cid, "caption": caption},
                files={"photo": ("checkin.jpg", photo_bytes, "image/jpeg")},
                timeout=10)
        except Exception as e:
            print(f"[TG PHOTO ERROR] {e}")

# ── Helpers ───────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_month_key(dt):
    return f"{dt.year}-M{dt.month:02d}"

def get_shift_times(shift, now):
    h = int(shift.split(":")[0])
    if h == 8:
        start = now.replace(hour=8,  minute=0, second=0, microsecond=0)
        end   = now.replace(hour=16, minute=0, second=0, microsecond=0)
    elif h == 16:
        start = now.replace(hour=16, minute=0, second=0, microsecond=0)
        end   = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # 00:00 night
        if now.hour >= 20:
            start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=8)
    return start, end

def calc_late(shift, now):
    start, _ = get_shift_times(shift, now)
    return max(0, int((now - start).total_seconds() / 60))

def format_late(m):
    if m <= 0: return "✅ On time"
    h, r = m // 60, m % 60
    return f"⏰ {h}h {r}min late" if h > 0 else f"⏰ {m} min late"

def format_dur(m):
    h, r = m // 60, m % 60
    if h > 0 and r > 0: return f"{h}h {r}min"
    if h > 0: return f"{h}h"
    return f"{m}min"

def format_total_late(m):
    if m <= 0: return "0 min"
    h, r = m // 60, m % 60
    if h > 0 and r > 0: return f"{h}h {r}min"
    if h > 0: return f"{h}h"
    return f"{m} min"

# ── Routes ────────────────────────────────────────────────

@app.route("/employees")
def get_employees():
    conn = get_db()
    rows = conn.execute("SELECT id, name, shift, off_day FROM employees").fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "name": r["name"], "shift": r["shift"],
                     "off_day": r["off_day"] or "None"} for r in rows])

@app.route("/checkin", methods=["POST"])
def checkin():
    """
    Принимает multipart/form-data:
      - employee_id: string
      - photo: image file
    Сохраняет в БД, считает штраф, отправляет фото менеджерам.
    """
    emp_id    = request.form.get("employee_id")
    photo_file = request.files.get("photo")

    if not emp_id:
        return jsonify({"ok": False, "error": "employee_id required"}), 400

    conn = get_db()

    # Найти сотрудника
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        return jsonify({"ok": False, "error": "Employee not found"}), 404

    now      = datetime.now()
    time_str = now.strftime("%H:%M")
    shift    = emp["shift"]
    name     = emp["name"]
    shift_labels = {"08:00": "Day: 08:00-16:00", "16:00": "Main: 16:00-00:00", "00:00": "Night: 00:00-08:00"}
    shift_label  = shift_labels.get(shift, shift)

    # Проверить нет ли уже активного check-in
    existing = conn.execute(
        "SELECT id FROM attendance WHERE employee_id=? AND checkout IS NULL ORDER BY id DESC LIMIT 1",
        (emp_id,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"ok": False, "error": f"{name} already checked in"}), 409

    # Off day check
    off_day    = emp["off_day"] or "None"
    today_name = now.strftime("%A")
    if off_day not in ("None", "No day off") and off_day == today_name:
        conn.close()
        return jsonify({"ok": False, "error": f"{name} has day off today"}), 403

    # Shift window — разрешено за 1 час до начала
    start, end = get_shift_times(shift, now)
    open_from  = start - timedelta(hours=1)
    if not (open_from <= now <= end):
        conn.close()
        return jsonify({"ok": False, "error": "Check-in not allowed outside shift window"}), 403

    # Посчитать опоздание
    late  = calc_late(shift, now)
    week  = get_month_key(now)

    # Сохранить в БД
    conn.execute(
        "INSERT INTO attendance (employee_id, checkin, late, week) VALUES (?,?,?,?)",
        (emp_id, now.isoformat(), late, week))
    conn.commit()

    # Посчитать общий штраф за месяц
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute(
        "SELECT SUM(late) FROM attendance WHERE employee_id=? AND week=? AND checkin>=?",
        (emp_id, week, month_start.isoformat())).fetchone()
    total_monthly_late = row[0] or 0
    total_monthly_fine = total_monthly_late
    fine_today         = late
    conn.close()

    late_str   = format_late(late)
    late_emoji = "🟢" if late <= 15 else "🟡" if late <= 30 else "🔴"

    caption = (
        f"{late_emoji} CHECK-IN\n\n"
        f"👤 {name} {emp_id}\n"
        f"📋 Shift: {shift_label}\n"
        f"🕒 Time: {time_str}\n"
        f"{late_str}\n"
        f"💸 Fine today: ${fine_today}\n"
        f"📊 Total Monthly Late: {format_total_late(total_monthly_late)}\n"
        f"💰 Total Monthly Fine: ${total_monthly_fine}"
    )

    # Отправить фото или текст менеджерам
    if photo_file:
        photo_bytes = photo_file.read()
        tg_photo(photo_bytes, caption)
    else:
        tg_send(caption)

    return jsonify({
        "ok": True,
        "late": late,
        "fine_today": fine_today,
        "total_monthly_late": total_monthly_late,
        "total_monthly_fine": total_monthly_fine
    })


@app.route("/checkout", methods=["POST"])
def checkout():
    """
    Принимает JSON: { "employee_id": "#J660" }
    Закрывает запись в БД, отправляет уведомление менеджерам.
    """
    data   = request.get_json() or {}
    emp_id = data.get("employee_id")

    if not emp_id:
        return jsonify({"ok": False, "error": "employee_id required"}), 400

    conn = get_db()
    emp  = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        return jsonify({"ok": False, "error": "Employee not found"}), 404

    now      = datetime.now()
    time_str = now.strftime("%H:%M")
    shift    = emp["shift"]
    name     = emp["name"]
    shift_labels = {"08:00": "Day: 08:00-16:00", "16:00": "Main: 16:00-00:00", "00:00": "Night: 00:00-08:00"}
    shift_label  = shift_labels.get(shift, shift)

    row = conn.execute(
        "SELECT id, checkin FROM attendance WHERE employee_id=? AND checkout IS NULL ORDER BY id DESC LIMIT 1",
        (emp_id,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "error": f"{name} has no active check-in"}), 404

    record_id, checkin_str = row["id"], row["checkin"]
    checkin_dt     = datetime.fromisoformat(checkin_str)
    worked_minutes = int((now - checkin_dt).total_seconds() / 60)

    _, end = get_shift_times(shift, now)
    early_minutes = max(0, int((end - now).total_seconds() / 60)) if now < end else 0

    if early_minutes >= 60:
        eh, em = early_minutes // 60, early_minutes % 60
        early_msg = f"\n⚠️ Left {eh}h {em}min early!" if em > 0 else f"\n⚠️ Left {eh}h early!"
    elif early_minutes > 0:
        early_msg = f"\n⚠️ Left {early_minutes} min early!"
    else:
        early_msg = ""

    conn.execute("UPDATE attendance SET checkout=? WHERE id=?", (now.isoformat(), record_id))
    conn.commit()
    conn.close()

    wh, wm = worked_minutes // 60, worked_minutes % 60
    text = (
        f"🔴 CHECK-OUT\n\n"
        f"👤 {name} {emp_id}\n"
        f"📋 Shift: {shift_label}\n"
        f"🕒 Time: {time_str}\n"
        f"⏱ Worked: {wh}h {wm}min{early_msg}"
    )
    tg_send(text)

    return jsonify({"ok": True, "worked_minutes": worked_minutes})


@app.route("/ping")
def ping():
    return jsonify({"ok": True, "time": datetime.now().isoformat()})

def keep_alive():
    url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")
    while True:
        time.sleep(600)  # 10 минут
        try:
            requests.get(f"{url}/ping", timeout=10)
            print(f"[KEEP-ALIVE] Pinged at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"[KEEP-ALIVE ERROR] {e}")

def run_bots():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from aiogram import Bot, Dispatcher
    import bot as bot_module
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_module.main())

if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=run_bots, daemon=True).start()
    print("✅ Server + Bots started")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)