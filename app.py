import os
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, Response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))

# ─────────────────────────── ГДЕ ЛЕЖИТ БАЗА ───────────────────────────
if os.environ.get("DATA_DIR"):
    DATA_DIR = os.environ["DATA_DIR"]
elif os.path.isdir("/data"):
    DATA_DIR = "/data"
else:
    DATA_DIR = basedir

os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "recovery.db")

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

try:
    app.json.ensure_ascii = False
except AttributeError:
    app.config["JSON_AS_ASCII"] = False

db = SQLAlchemy(app)

# ─────────────────────────────── МОДЕЛИ ───────────────────────────────

class Profile(db.Model):
    __tablename__ = "profile"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    days = db.Column(db.Integer, default=0)
    slips_avoided = db.Column(db.Integer, default=0)
    start_time = db.Column(db.String(100), nullable=True)

class CbtRecord(db.Model):
    __tablename__ = "cbt_record"
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False)
    automatic_thought = db.Column(db.Text, nullable=False)
    rational_response = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(50), nullable=False)

class Letter(db.Model):
    __tablename__ = "letter"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(50), nullable=False)

class WorkoutRecord(db.Model):
    __tablename__ = "workout_record"
    id = db.Column(db.Integer, primary_key=True)
    workout_type = db.Column(db.String(100), nullable=False)
    exercise_name = db.Column(db.String(150), nullable=False)
    reps_data = db.Column(db.String(100), nullable=False)
    date = db.Column(db.String(50), nullable=False)

class StrategyBoard(db.Model):
    __tablename__ = "strategy_board"
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, default="")

class DayMark(db.Model):
    __tablename__ = "day_mark"
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), unique=True, index=True, nullable=False)
    status = db.Column(db.String(10), nullable=True)
    note = db.Column(db.Text, default="")

class BalanceLog(db.Model):
    __tablename__ = "balance_log"
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), unique=True, index=True, nullable=False)
    index = db.Column(db.Integer, default=0)
    boosters = db.Column(db.Integer, default=0)
    traps = db.Column(db.Integer, default=0)
    boosters_detail = db.Column(db.String(255), default="")
    traps_detail = db.Column(db.String(255), default="")

with app.app_context():
    db.create_all()

print("✅ База данных готова")
print("Путь к базе:", DB_PATH)

# ─────────────────────────── ВСПОМОГАТЕЛЬНОЕ ───────────────────────────

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_profile():
    return Profile.query.first()

def get_board():
    board = StrategyBoard.query.first()
    if not board:
        board = StrategyBoard(content="1. Беречь спину, избегать осевых нагрузок\n2. Фокус на глубокие мышцы кора\n3. Регулярная растяжка и разминка")
        db.session.add(board)
        db.session.commit()
    return board

def state_payload():
    profile = get_profile()
    board = get_board()
    marks = DayMark.query.all()
    logs = BalanceLog.query.order_by(BalanceLog.day.asc()).all()
    cbt = CbtRecord.query.order_by(CbtRecord.id.desc()).all()
    letters = Letter.query.order_by(Letter.id.desc()).all()
    workouts = WorkoutRecord.query.order_by(WorkoutRecord.id.desc()).all()

    return {
        "ok": True,
        "storage": {
            "dir": DATA_DIR,
            "persistent": os.path.abspath(DATA_DIR) != os.path.abspath(basedir),
        },
        "profile": None if profile is None else {
            "name": profile.name,
            "days": profile.days or 0,
            "slips_avoided": profile.slips_avoided or 0,
            "start_time": profile.start_time,
        },
        "board_content": board.content if board else "",
        "marks": {
            m.day: {"status": m.status, "note": m.note or ""} for m in marks
        },
        "balance_logs": [
            {
                "day": l.day,
                "index": l.index or 0,
                "boosters": l.boosters or 0,
                "traps": l.traps or 0,
                "boosters_detail": [k for k in (l.boosters_detail or "").split(",") if k],
                "traps_detail": [k for k in (l.traps_detail or "").split(",") if k],
            }
            for l in logs
        ],
        "cbt_records": [
            {
                "id": c.id,
                "category": c.category,
                "automatic_thought": c.automatic_thought,
                "rational_response": c.rational_response,
                "date": c.date,
            }
            for c in cbt
        ],
        "letters": [
            {
                "id": l.id,
                "title": l.title,
                "content": l.content,
                "date": l.date,
            }
            for l in letters
        ],
        "workouts": [
            {
                "id": w.id,
                "workout_type": w.workout_type,
                "exercise_name": w.exercise_name,
                "reps_data": w.reps_data,
                "date": w.date,
            }
            for w in workouts
        ],
    }

# ─────────────────────────────── РРОУТЫ ───────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state")
def api_state():
    return jsonify(state_payload())

@app.route("/api/profile", methods=["POST"])
def api_profile():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:100] or "Боец"
    try:
        days = max(0, int(data.get("days") or 0))
    except (TypeError, ValueError):
        days = 0

    start_dt = datetime.now() - timedelta(days=days)

    profile = get_profile()
    if profile:
        profile.name = name
        profile.days = days
        profile.start_time = start_dt.isoformat()
    else:
        db.session.add(Profile(
            name=name,
            days=days,
            slips_avoided=0,
            start_time=start_dt.isoformat(),
        ))

    db.session.commit()
    return jsonify(state_payload())

@app.route("/api/day/add", methods=["POST"])
def api_day_add():
    profile = get_profile()
    if profile is None:
        return jsonify({"ok": False, "error": "Профиль ещё не создан"}), 400

    profile.days = max(0, (profile.days or 0) + 1)
    key = today_str()
    mark = DayMark.query.filter_by(day=key).first()
    if mark is None:
        mark = DayMark(day=key, note="")
        db.session.add(mark)
    mark.status = "win"

    db.session.commit()
    return jsonify(state_payload())

@app.route("/api/sos", methods=["POST"])
def api_sos():
    profile = get_profile()
    if profile is not None:
        profile.slips_avoided = (profile.slips_avoided or 0) + 1
        db.session.commit()
    return jsonify(state_payload())

@app.route("/api/mark", methods=["POST"])
def api_mark():
    data = request.get_json(silent=True) or {}
    day = (data.get("day") or "").strip()
    status = (data.get("status") or "").strip() or None
    note = (data.get("note") or "").strip()

    if not day:
        return jsonify({"ok": False, "error": "Не передана дата"}), 400

    mark = DayMark.query.filter_by(day=day).first()
    if status is None and not note:
        if mark is not None:
            db.session.delete(mark)
            db.session.commit()
        return jsonify(state_payload())

    if mark is None:
        mark = DayMark(day=day, note="")
        db.session.add(mark)

    mark.status = status
    mark.note = note
    db.session.commit()
    return jsonify(state_payload())

@app.route("/api/balance", methods=["POST"])
def api_balance():
    data = request.get_json(silent=True) or {}
    day = (data.get("day") or today_str()).strip()
    booster_keys = [str(v)[:32] for v in (data.get("boosters") or []) if str(v).strip()]
    trap_keys = [str(v)[:32] for v in (data.get("traps") or []) if str(v).strip()]

    boosters = len(booster_keys)
    traps = len(trap_keys)
    index = boosters * 2 - traps * 2

    log = BalanceLog.query.filter_by(day=day).first()
    if log is None:
        log = BalanceLog(day=day)
        db.session.add(log)
    log.boosters = boosters
    log.traps = traps
    log.index = index
    log.boosters_detail = ",".join(booster_keys)[:255]
    log.traps_detail = ",".join(trap_keys)[:255]

    mark = DayMark.query.filter_by(day=day).first()
    if mark is None:
        mark = DayMark(day=day, note="")
        db.session.add(mark)
    mark.status = "win" if index >= 0 else "slip"

    db.session.commit()
    return jsonify(state_payload())

@app.route("/api/cbt", methods=["POST"])
def api_cbt():
    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()[:100] or "Общее"
    thought = (data.get("automatic_thought") or "").strip()
    response = (data.get("rational_response") or "").strip()

    if thought and response:
        db.session.add(CbtRecord(
            category=category,
            automatic_thought=thought,
            rational_response=response,
            date=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ))
        db.session.commit()

    return jsonify(state_payload())

@app.route("/api/cbt/import", methods=["POST"])
def api_cbt_import():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if text:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        for p in paragraphs:
            db.session.add(CbtRecord(
                category="Улица / Google Docs",
                automatic_thought=p,
                rational_response="[Импорт с телефона — ждет анализа и рационализации]",
                date=date_str,
            ))
        db.session.commit()
    return jsonify(state_payload())

@app.route("/api/letter", methods=["POST"])
def api_letter():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:150]
    content = (data.get("content") or "").strip()

    if title and content:
        db.session.add(Letter(
            title=title,
            content=content,
            date=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ))
        db.session.commit()

    return jsonify(state_payload())

@app.route("/api/workout", methods=["POST"])
def api_workout():
    data = request.get_json(silent=True) or {}
    w_type = (data.get("workout_type") or "").strip()[:100]
    ex_name = (data.get("exercise_name") or "").strip()[:150]
    reps = (data.get("reps_data") or "").strip()[:100]

    if w_type and ex_name and reps:
        db.session.add(WorkoutRecord(
            workout_type=w_type,
            exercise_name=ex_name,
            reps_data=reps,
            date=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ))
        db.session.commit()

    return jsonify(state_payload())

@app.route("/api/workout/delete", methods=["POST"])
def api_workout_delete():
    data = request.get_json(silent=True) or {}
    w_id = data.get("id")
    if w_id:
        record = WorkoutRecord.query.get(w_id)
        if record:
            db.session.delete(record)
            db.session.commit()
    return jsonify(state_payload())

@app.route("/api/board", methods=["POST"])
def api_board():
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    board = get_board()
    board.content = content
    db.session.commit()
    return jsonify(state_payload())

@app.route("/api/reset", methods=["POST"])
def api_reset():
    DayMark.query.delete()
    BalanceLog.query.delete()
    CbtRecord.query.delete()
    Letter.query.delete()
    WorkoutRecord.query.delete()
    StrategyBoard.query.delete()
    Profile.query.delete()
    db.session.commit()
    return jsonify(state_payload())

@app.route("/export_cbt")
def export_cbt():
    records = CbtRecord.query.order_by(CbtRecord.id.desc()).all()
    text_data = "=== RECOVERY HUB: АРХИВ КПТ-РАЗБОРОВ (АНТИ-ТРЕВОГА) ===\n\n"
    for r in records:
        text_data += f"📅 Дата: {r.date}\n🏷️ Категория: {r.category}\n🧠 Автоматическая мысль: {r.automatic_thought}\n💡 Рациональный ответ: {r.rational_response}\n" + "-" * 50 + "\n\n"

    return Response(
        text_data,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-disposition": "attachment; filename=cbt_recovery_log.txt"},
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)