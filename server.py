from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import psycopg2, psycopg2.extras, requests, os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UZB_TZ = ZoneInfo("Asia/Tashkent")

def now_uzb():
    return datetime.now(UZB_TZ).replace(tzinfo=None)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(BASE_DIR, "frontend", "dist")

app = Flask(__name__, static_folder=BUILD_DIR, static_url_path="")
CORS(app)

# ── Замени [YOUR-PASSWORD] на свой пароль ──────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:[YOUR-PASSWORD]@db.vwqsjayrinopywfmbuib.supabase.co:5432/postgres"
)

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

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def init_db():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id          SERIAL PRIMARY KEY,
            employee_id TEXT,
            checkin     TEXT,
            checkout    TEXT,
            late        INTEGER,
            week        TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id      TEXT PRIMARY KEY,
            name    TEXT,
            shift   TEXT,
            off_day TEXT DEFAULT 'None'
        )
    """)
    cur.execute("SELECT COUNT(*) FROM employees")
    if cur.fetchone()[0] == 0:
        for e in DEFAULT_EMPLOYEES:
            cur.execute(
                "INSERT INTO employees (id, name, shift, off_day) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                e
            )
    conn.commit()
    cur.close(); conn.close()
    print("[DB] PostgreSQL ready (Supabase)")

init_db()

BOT_TOKEN   = "8758406348:AAEjNIPMChEc1gZ3IQlh7aUCShVwutGHOFU"
MANAGER_IDS = ["5952683615", "39730332", "8473394162"]

def tg_send(text):
    for cid in MANAGER_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": text}, timeout=5
            )
        except Exception as e:
            print(f"[TG] {e}")

def tg_photo(photo_bytes, caption):
    for cid in MANAGER_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": cid, "caption": caption},
                files={"photo": ("checkin.jpg", photo_bytes, "image/jpeg")}, timeout=10
            )
        except Exception as e:
            print(f"[TG PHOTO] {e}")

def get_month_key(dt):
    return f"{dt.year}-M{dt.month:02d}"

def get_shift_times(shift, now):
    h = int(shift.split(":")[0])
    if h == 8:
        s = now.replace(hour=8,  minute=0, second=0, microsecond=0)
        e = now.replace(hour=16, minute=0, second=0, microsecond=0)
    elif h == 16:
        s = now.replace(hour=16, minute=0, second=0, microsecond=0)
        e = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        base = (now + timedelta(days=1)) if now.hour >= 20 else now
        s = base.replace(hour=0, minute=0, second=0, microsecond=0)
        e = s + timedelta(hours=8)
    return s, e

def calc_late(shift, now):
    s, _ = get_shift_times(shift, now)
    diff = int((now - s).total_seconds() / 60)
    if diff <= 0 or diff > 480:
        return 0
    return diff

def fmt_late(m):
    if m <= 0: return "✅ On time"
    h, r = m // 60, m % 60
    return (f"⏰ {h}h {r}min late" if h else f"⏰ {m} min late")

def fmt_total(m):
    if m <= 0: return "0 min"
    h, r = m // 60, m % 60
    if h and r: return f"{h}h {r}min"
    return f"{h}h" if h else f"{m} min"

SHIFT_LABELS = {
    "08:00": "Day: 08:00-16:00",
    "16:00": "Main: 16:00-00:00",
    "00:00": "Night: 00:00-08:00"
}

# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/employees")
def get_employees():
    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, name, shift, off_day FROM employees")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([
        {"id": r["id"], "name": r["name"], "shift": r["shift"], "off_day": r["off_day"] or "None"}
        for r in rows
    ])

@app.route("/checkin", methods=["POST"])
def checkin():
    emp_id     = request.form.get("employee_id")
    photo_file = request.files.get("photo")
    if not emp_id:
        return jsonify({"ok": False, "error": "employee_id required"}), 400

    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM employees WHERE id=%s", (emp_id,))
    emp = cur.fetchone()
    if not emp:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": "Employee not found"}), 404

    now   = now_uzb()
    shift = emp["shift"]
    name  = emp["name"]

    cur.execute(
        "SELECT id FROM attendance WHERE employee_id=%s AND checkout IS NULL ORDER BY id DESC LIMIT 1",
        (emp_id,)
    )
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": f"{name} already checked in"}), 409

    off = emp["off_day"] or "None"
    if off not in ("None", "No day off") and off == now.strftime("%A"):
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": f"{name} has day off today"}), 403

    s, e = get_shift_times(shift, now)
    earliest = s - timedelta(hours=2)
    if now < earliest:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": f"Too early! Check-in opens at {earliest.strftime('%H:%M')}"}), 403
    if now > e:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": f"Shift already ended! Was {s.strftime('%H:%M')} — {e.strftime('%H:%M')}"}), 403

    late = calc_late(shift, now)
    week = get_month_key(now)
    cur.execute(
        "INSERT INTO attendance (employee_id, checkin, late, week) VALUES (%s,%s,%s,%s)",
        (emp_id, now.isoformat(), late, week)
    )
    conn.commit()

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cur.execute(
        "SELECT SUM(late) FROM attendance WHERE employee_id=%s AND checkin>=%s",
        (emp_id, month_start.isoformat())
    )
    total = cur.fetchone()["sum"] or 0
    cur.close(); conn.close()

    late_status = f"⏰ Late: {late} min  💸 Fine: ${late}" if late > 0 else "✅ On time"
    cap = (
        f"🟢 CHECK-IN\n\n👤 {name} {emp_id}\n📋 Shift: {SHIFT_LABELS.get(shift, shift)}\n"
        f"🕒 Time: {now.strftime('%H:%M')}\n{late_status}\n"
        f"📊 Monthly late: {fmt_total(total)}\n💰 Monthly fine: ${total}"
    )
    if photo_file:
        tg_photo(photo_file.read(), cap)
    else:
        tg_send(cap)

    return jsonify({"ok": True, "late": late, "fine_today": late,
                    "total_monthly_late": total, "total_monthly_fine": total})

@app.route("/checkout", methods=["POST"])
def checkout():
    data   = request.get_json() or {}
    emp_id = data.get("employee_id")
    if not emp_id:
        return jsonify({"ok": False, "error": "employee_id required"}), 400

    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM employees WHERE id=%s", (emp_id,))
    emp = cur.fetchone()
    if not emp:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": "Employee not found"}), 404

    now   = now_uzb()
    shift = emp["shift"]
    name  = emp["name"]

    cur.execute(
        "SELECT id, checkin FROM attendance WHERE employee_id=%s AND checkout IS NULL ORDER BY id DESC LIMIT 1",
        (emp_id,)
    )
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": f"{name} has no active check-in"}), 404

    ci_dt  = datetime.fromisoformat(row["checkin"])
    worked = int((now - ci_dt).total_seconds() / 60)
    _, e   = get_shift_times(shift, now)
    early  = max(0, int((e - now).total_seconds() / 60)) if now < e else 0

    if early >= 60:
        h, m = early // 60, early % 60
        em = f"\n⚠️ Left {h}h {m}min early!" if m else f"\n⚠️ Left {h}h early!"
    elif early > 0:
        em = f"\n⚠️ Left {early} min early!"
    else:
        em = ""

    cur.execute("UPDATE attendance SET checkout=%s WHERE id=%s", (now.isoformat(), row["id"]))
    conn.commit()
    cur.close(); conn.close()

    wh, wm = worked // 60, worked % 60
    tg_send(
        f"🔴 CHECK-OUT\n\n👤 {name} {emp_id}\n📋 Shift: {SHIFT_LABELS.get(shift, shift)}\n"
        f"🕒 Time: {now.strftime('%H:%M')}\n⏱ Worked: {wh}h {wm}min{em}"
    )
    return jsonify({"ok": True, "worked_minutes": worked})

@app.route("/update_offday", methods=["POST"])
def update_offday():
    data    = request.get_json() or {}
    emp_id  = data.get("employee_id")
    off_day = data.get("off_day", "No day off")
    if not emp_id:
        return jsonify({"ok": False, "error": "employee_id required"}), 400

    valid = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","No day off","None"]
    if off_day not in valid:
        return jsonify({"ok": False, "error": "invalid off_day value"}), 400

    conn = get_db()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM employees WHERE id=%s", (emp_id,))
    emp = cur.fetchone()
    if not emp:
        cur.close(); conn.close()
        return jsonify({"ok": False, "error": "Employee not found"}), 404

    cur.execute("UPDATE employees SET off_day=%s WHERE id=%s", (off_day, emp_id))
    conn.commit()
    cur.close(); conn.close()

    tg_send(f"📅 OFF DAY UPDATED\n\n👤 {emp['name']} {emp_id}\n🗓 Off day: {off_day}")
    return jsonify({"ok": True, "employee_id": emp_id, "off_day": off_day})

# ── React Frontend ─────────────────────────────────────────────────────────────
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    target = os.path.join(BUILD_DIR, path)
    if path and os.path.exists(target):
        return send_from_directory(BUILD_DIR, path)
    return send_from_directory(BUILD_DIR, "index.html")

if __name__ == "__main__":
    print("✅ Server → http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)