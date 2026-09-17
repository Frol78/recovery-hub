import os

from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, Response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))

# ─────────────────────────── ГДЕ ЛЕЖИТ БАЗА ───────────────────────────
# Если в Amvera подключён постоянный диск, его путь приходит в DATA_DIR
# (переменная окружения). Тогда база живёт на диске и переживает
# пересборку контейнера. Если диска нет — база ложится рядом с app.py,
# но при каждом деплое она обнуляется. В ответе /api/state поле
# storage.persistent показывает текущий режим.
# Порядок приоритетов:
#   1. DATA_DIR из переменных окружения (задаётся в панели Amvera)
#   2. /data — путь постоянного диска Amvera (persistenceMount)
#   3. папка проекта — только локальная разработка, данные не переживут деплой
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
    app.json.ensure_ascii = False          # Flask 2.3+
except AttributeError:
    app.config["JSON_AS_ASCII"] = False    # Flask 2.2 и старше

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
    """Капсула трезвости: письма себе в моменты ясности."""
    __tablename__ = "letter"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(50), nullable=False)

class DayMark(db.Model):
    """Отметка одного дня в календаре «Карта чистоты»."""
    __tablename__ = "day_mark"
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), unique=True, index=True, nullable=False)  # YYYY-MM-DD
    status = db.Column(db.String(10), nullable=True)                          # win | slip
    note = db.Column(db.Text, default="")

class BalanceLog(db.Model):
    """Ежедневный баланс дофамина: бустеры, ловушки, индекс."""
    __tablename__ = "balance_log"
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), unique=True, index=True, nullable=False)  # YYYY-MM-DD
    index = db.Column(db.Integer, default=0)
    boosters = db.Column(db.Integer, default=0)
    traps = db.Column(db.Integer, default=0)
    boosters_detail = db.Column(db.String(255), default="")
    traps_detail = db.Column(db.String(255), default="")

with app.app_context():
    db.create_all()

print("✅ База данных готова")
print("Путь к базе:", DB_PATH)
print("Постоянное хранилище:", os.path.abspath(DATA_DIR) != os.path.abspath(basedir))

# ─────────────────────────── ВСПОМОГАТЕЛЬНОЕ ───────────────────────────
# Единственный формат ответа: полный слепок состояния. Клиент не хранит
# ничего у себя — он всегда получает правду с сервера и перерисовывает UI.
# Так данные одинаковы на ноутбуке, телефоне и в любом браузере.

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_profile():
    return Profile.query.first()

def state_payload():
    profile = get_profile()
    marks = DayMark.query.all()
    logs = BalanceLog.query.order_by(BalanceLog.day.asc()).all()
    cbt = CbtRecord.query.order_by(CbtRecord.id.desc()).all()
    letters = Letter.query.order_by(Letter.id.desc()).all()

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
    }

# ─────────────────────────────── СТРАНИЦА ───────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state")
def api_state():
    """Полный слепок: и при загрузке страницы, и как ответ на любую запись."""
    return jsonify(state_payload())

# ─────────────────────────── ЗАПИСЬ СОСТОЯНИЯ ───────────────────────────

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
    data = request.get_json(silent=True) or {}
    try:
        delta = int(data.get("add_days") or 1)
    except (TypeError, ValueError):
        delta = 1

    profile = get_profile()
    if profile is None:
        return jsonify({"ok": False, "error": "Профиль ещё не создан"}), 400

    profile.days = max(0, (profile.days or 0) + delta)

    # Заодно отмечаем сегодняшний день как чистый
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
    if status not in (None, "win", "slip"):
        return jsonify({"ok": False, "error": "Неизвестный статус"}), 400

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
    """Индекс считает сервер — клиент присылает только галочки."""
    data = request.get_json(silent=True) or {}

    day = (data.get("day") or today_str()).strip()

    def as_keys(value):
        """Принимает либо список ключей, либо число — и приводит к списку."""
        if isinstance(value, list):
            return [str(v)[:32] for v in value if str(v).strip()]
        try:
            return ["key"] * max(0, int(value or 0))
        except (TypeError, ValueError):
            return []

    booster_keys = as_keys(data.get("boosters"))
    trap_keys = as_keys(data.get("traps"))

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

    # Синхронизация с календарём: индекс >= 0 → день засчитан чистым
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

@app.route("/api/reset", methods=["POST"])
def api_reset():
    DayMark.query.delete()
    BalanceLog.query.delete()
    CbtRecord.query.delete()
    Letter.query.delete()
    Profile.query.delete()
    db.session.commit()
    return jsonify(state_payload())

@app.route("/export_cbt")
def export_cbt():
    records = CbtRecord.query.order_by(CbtRecord.id.desc()).all()

    text_data = "=== RECOVERY HUB: АРХИВ КПТ-РАЗБОРОВ (АНТИ-ТРЕВОГА) ===\n\n"
    for r in records:
        text_data += f"📅 Дата: {r.date}\n"
        text_data += f"🏷️ Категория: {r.category}\n"
        text_data += f"🧠 Автоматическая мысль: {r.automatic_thought}\n"
        text_data += f"💡 Рациональный ответ: {r.rational_response}\n"
        text_data += "-" * 50 + "\n\n"

    return Response(
        text_data,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-disposition": "attachment; filename=cbt_recovery_log.txt"},
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)