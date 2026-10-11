import os
import json
import math
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))

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
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-change-in-production")

# Настройка логина и пароля
AUTH_USER = os.environ.get("AUTH_USER", "Evgeniy")
AUTH_PASS = os.environ.get("AUTH_PASS", "04_07_1993$")

try:
    app.json.ensure_ascii = False
except AttributeError:
    app.config["JSON_AS_ASCII"] = False

db = SQLAlchemy(app)

# ==========================================
# ВЕСА ФАКТОРОВ ВЫЗДОРОВЛЕНИЯ (УМНЫЙ СКОРИНГ)
# ==========================================
BOOSTER_WEIGHTS = {
    "physics_action": 35,
    "cbt_written": 25,
    "clean_victory": 30,
    "coding_flow": 15,
    "body_care": 15,
    "Здоровый сон (режим в норме)": 15,
    "Продуктивный кодинг": 15,
    "Спорт / Тело / Йога": 15,
    "Чистый день без кофе": 10,
}

TRAP_WEIGHTS = {
    "micro_slip": -30,
    "loneliness_pity": -20,
    "news_overload": -15,
    "coding_frustration": -10,
    "sleep_disrupt": -10,
    "Кофеин-триггер (тревога)": -10,
    "Сбой сна (долгий/поздний)": -10,
    "Боль в спине / Остеохондроз": -15,
    "Жалость к себе": -20,
    "Тупняк за ноутом / Прокрастинация": -10,
}

# ==========================================
# ТЕКСТЫ СИМУЛЯТОРА РАЗВИЛКИ
# Правь формулировки ЗДЕСЬ — фронт забирает их как есть.
# ==========================================
FORECAST_META = {
    "horizon_default": 30,
    "horizon_max": 180,
    "series": {
        "strength": {"label": "Путь силы", "desc": "Реальность, если выстоишь и не заплатишь зависимости"},
        "slip":     {"label": "Путь срыва", "desc": "Реальность, если сдашься прямо сейчас"},
        "mirage":   {"label": "Мираж зависимости", "desc": "То, что она обещает в момент тяги"},
    },
    "slip_consequences": [
        {"icon": "📉", "title": "Дофаминовая яма",
         "text": "10 минут фантомного кайфа — и 3–5 дней серости. Ничего не радует: ни музыка, ни код, ни люди."},
        {"icon": "⚡", "title": "Сосуды и потенция",
         "text": "Хронический перегруз дофамином и сосудистый спазм бьют по эрекции. Это физиология, а не миф, и лечится она только воздержанием."},
        {"icon": "🧠", "title": "Укрепление старой связи",
         "text": "Каждый срыв протаптывает нейронную дорожку глубже. В следующий раз тянуть будет сильнее и быстрее."},
        {"icon": "⏳", "title": "Обнуление серии",
         "text": "Счётчик чистого времени уходит в ноль. Всё, что наработал днями, стирается за одну секунду."},
        {"icon": "🪞", "title": "Удар по самооценке",
         "text": "Стыд, торг, обесценивание себя. Ты снова тот, кто не держит слово даже перед самим собой."},
        {"icon": "🎯", "title": "Крадёт дни у цели",
         "text": "Счётчик пути не обнулится — цель остаётся твоей опорой. Но время срыва не вернуть: день, отданный зависимости, не вложен в себя. Счётчик идёт, а ты топчешься."},
    ],
    "strength_gains": [
        {"icon": "🛡️", "title": "Связь слабеет",
         "text": "Ты не заплатил зависимости. Дорожка сужается, а не расширяется — в следующий раз тянуть будет тише."},
        {"icon": "🔥", "title": "Энергия остаётся в тебе",
         "text": "Тестостерон, чувствительность рецепторов, ясность в голове — всё это остаётся в теле, а не сливается в унитаз."},
        {"icon": "🎯", "title": "+1 день к цели",
         "text": "Ты ближе к цели ровно на сутки. Сухие цифры, которые без пафоса складываются в новую жизнь."},
        {"icon": "🧱", "title": "Тренировка характера",
         "text": "Каждый пройденный шторм — это подход к штанге для воли. Ты становишься тем, кто держит слово."},
        {"icon": "🌈", "title": "Возврат красок",
         "text": "Реальность отдаёт обратно вкус: еда, музыка, работа, люди снова цепляют по-настоящему."},
        {"icon": "🪞", "title": "Самоуважение",
         "text": "Утром ты смотришь в зеркало без омерзения. Это дороже любого фантомного кайфа."},
    ],
}


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != AUTH_USER or auth.password != AUTH_PASS:
            return Response(
                "Доступ ограничен. Требуется авторизация.",
                401,
                {"WWW-Authenticate": 'Basic realm="Recovery Hub Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated


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
    bad_sleep = db.Column(db.Boolean, default=False)
    back_pain = db.Column(db.Boolean, default=False)
    isolation = db.Column(db.Boolean, default=False)


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


class DailyGoal(db.Model):
    __tablename__ = "daily_goal"
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False, index=True)
    text = db.Column(db.String(255), nullable=False)
    completed = db.Column(db.Boolean, default=False)


# ---------- НОВОЕ: фундамент судьбы ----------
class LifeGoal(db.Model):
    """Глобальная карта: кто я, откуда иду, куда иду."""
    __tablename__ = "life_goal"
    id = db.Column(db.Integer, primary_key=True)
    age = db.Column(db.Integer, default=33)
    past_dependencies = db.Column(db.Text, default="[]")   # JSON-список пройденного
    current_dependency = db.Column(db.String(150), default="")
    dependency_gives = db.Column(db.Text, default="")      # что она даёт / от чего ухожу
    goal_title = db.Column(db.String(200), default="")
    goal_description = db.Column(db.Text, default="")
    goal_days_target = db.Column(db.Integer, default=365)
    started_at = db.Column(db.String(100), nullable=True)
    updated_at = db.Column(db.String(100), nullable=True)


class GoalStep(db.Model):
    """Конкретные шаги, которые ты реально сделал в сторону цели."""
    __tablename__ = "goal_step"
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255), nullable=False)
    weight = db.Column(db.Integer, default=1)
    done = db.Column(db.Boolean, default=False)
    date = db.Column(db.String(50), nullable=False)


class UrgeLog(db.Model):
    """Точка выбора: накрыла тяга — что выбрал."""
    __tablename__ = "urge_log"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.String(50), nullable=False)          # ISO timestamp
    day = db.Column(db.String(10), nullable=False, index=True)
    intensity = db.Column(db.Integer, default=5)           # 1..10
    trigger = db.Column(db.String(255), default="")
    note = db.Column(db.Text, default="")
    choice = db.Column(db.String(15), default="pending")   # pending / strength / slip
    resolved_at = db.Column(db.String(50), default="")
    days_at_stake = db.Column(db.Integer, default=0)


def _ensure_column(table, column, ddl_type):
    """Безопасно добавляет колонку в существующую таблицу. Ничего не удаляет."""
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
            conn.commit()
    except Exception:
        pass


def _sqlite_type_for(column):
    """Простой SQLite-тип под колонку модели (для ALTER TABLE)."""
    try:
        py = column.type.python_type
    except Exception:
        return "TEXT"
    if py is bool:
        return "BOOLEAN"
    if py is int:
        return "INTEGER"
    if py is float:
        return "REAL"
    return "TEXT"


def _default_clause(column):
    """Значение по умолчанию, чтобы старые строки не остались NULL."""
    t = _sqlite_type_for(column)
    return " DEFAULT 0" if t in ("INTEGER", "REAL", "BOOLEAN") else " DEFAULT ''"


def sync_schema():
    """Приводит существующую базу к текущим моделям.

    db.create_all() создаёт только НЕДОСТАЮЩИЕ таблицы и никогда не трогает уже
    существующие. Поэтому база от прошлой версии приложения остаётся со старым
    набором колонок — и любой запрос к такой таблице падает с 500
    («no such column»). Здесь дописываются только недостающие колонки:
    ничего не удаляется, не переименовывается и не теряется.
    """
    added = []
    try:
        inspector = db.inspect(db.engine)
        for model in db.Model.__subclasses__():
            table = getattr(model, "__tablename__", None)
            if not table:
                continue
            try:
                if not inspector.has_table(table):
                    continue
                existing = {c["name"] for c in inspector.get_columns(table)}
            except Exception:
                continue
            for column in model.__table__.columns:
                if column.name in existing:
                    continue
                ddl = _sqlite_type_for(column) + _default_clause(column)
                try:
                    with db.engine.connect() as conn:
                        conn.execute(db.text(
                            'ALTER TABLE "' + table + '" ADD COLUMN "' + column.name + '" ' + ddl
                        ))
                        conn.commit()
                    added.append(table + "." + column.name)
                except Exception as e:
                    print("⚠️ Не удалось добавить " + table + "." + column.name + ":", e)
    except Exception as e:
        print("⚠️ Сверка схемы пропущена:", e)
    if added:
        print("🔧 Дописаны недостающие колонки:", ", ".join(added))
    return added


with app.app_context():
    db.create_all()
    sync_schema()
    # Страховка для самых старых баз: этих колонок в КПТ могло не быть.
    _ensure_column("cbt_record", "bad_sleep", "BOOLEAN DEFAULT 0")
    _ensure_column("cbt_record", "back_pain", "BOOLEAN DEFAULT 0")
    _ensure_column("cbt_record", "isolation", "BOOLEAN DEFAULT 0")

print("✅ База данных готова:", DB_PATH)


# ==========================================
# ХЕЛПЕРЫ
# ==========================================
def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def get_profile():
    return Profile.query.first()


def get_life_goal():
    return LifeGoal.query.first()


def get_board():
    board = StrategyBoard.query.first()
    if not board:
        board = StrategyBoard(content="1. Беречь спину, избегать осевых нагрузок\n2. Фокус на глубокие мышцы кора\n3. Регулярная растяжка и разминка")
        db.session.add(board)
        db.session.commit()
    return board


def parse_slip_note(note_str):
    if not note_str:
        return None
    try:
        data = json.loads(note_str)
        if isinstance(data, dict) and "trigger" in data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def target_days():
    goal = get_life_goal()
    if goal and goal.goal_days_target:
        return max(1, int(goal.goal_days_target))
    return 365


def goal_days_in():
    """Сколько дней идёт текущая глобальная цель."""
    goal = get_life_goal()
    started = None
    if goal and goal.started_at:
        try:
            started = datetime.fromisoformat(goal.started_at)
        except (ValueError, TypeError):
            started = None
    if started is None:
        profile = get_profile()
        if profile and profile.start_time:
            try:
                started = datetime.fromisoformat(profile.start_time)
            except (ValueError, TypeError):
                started = None
    if started is None:
        return 0
    return max(0, (datetime.now() - started).days)


def apply_slip(note_text):
    """Один общий путь срыва: помечаем день и обнуляем таймер."""
    day = today_str()
    mark = DayMark.query.filter_by(day=day).first()
    if mark is None:
        mark = DayMark(day=day, note="")
        db.session.add(mark)
    mark.status = "slip"
    mark.note = note_text

    profile = get_profile()
    if profile:
        profile.start_time = datetime.now().isoformat()
        profile.days = 0
    return mark


def life_goal_payload():
    goal = get_life_goal()
    if goal is None:
        return None
    try:
        past = json.loads(goal.past_dependencies or "[]")
        if not isinstance(past, list):
            past = []
    except (json.JSONDecodeError, TypeError):
        past = []
    days_in = goal_days_in()
    tgt = target_days()
    return {
        "age": goal.age or 33,
        "past_dependencies": past,
        "current_dependency": goal.current_dependency or "",
        "dependency_gives": goal.dependency_gives or "",
        "goal_title": goal.goal_title or "",
        "goal_description": goal.goal_description or "",
        "goal_days_target": tgt,
        "started_at": goal.started_at,
        "updated_at": goal.updated_at,
        "days_in": days_in,
        "progress_pct": round(min(100.0, 100.0 * days_in / tgt), 1) if tgt else 0.0,
    }


# ==========================================
# ПРОГНОЗНЫЙ ДВИЖОК (ТРИ КРИВЫЕ)
# ==========================================
def _strength_value(t, target):
    """Путь силы: плавный рост к 100 с насыщением."""
    if target <= 0:
        target = 365
    return 100.0 * (1.0 - math.exp(-2.4 * t / float(target)))


def _mirage_curve(start_val, horizon):
    """Мираж: мозг обещает подъём, реальность падает ниже всех."""
    floor = -45.0
    peak = min(100.0, start_val + 15.0)
    out = []
    for d in range(horizon + 1):
        if d == 0:
            out.append(round(start_val, 2))
        elif d == 1:
            out.append(round(peak, 2))
        elif d == 2:
            out.append(round(start_val - 5.0, 2))
        else:
            k = 2.4 * (d - 2) / max(1.0, horizon / 3.0)
            out.append(round(max(floor, start_val - 5.0 - (start_val + 5.0 - floor) * (1.0 - math.exp(-k))), 2))
    return out


def _slip_curve(start_val, horizon):
    """Путь срыва: резко вниз и долгий выход со дна."""
    floor = -20.0
    out = []
    for d in range(horizon + 1):
        if d == 0:
            out.append(round(start_val, 2))
        else:
            k = 2.2 * d / max(1.0, horizon / 2.5)
            out.append(round(max(floor, floor + (start_val - floor) * math.exp(-k)), 2))
    return out


def build_forecast(horizon=30, start_val=None, target=None):
    if start_val is None:
        start_val = min(100.0, round(100.0 * goal_days_in() / max(1, target_days()), 2))
    if target is None:
        target = target_days()
    horizon = max(1, min(int(horizon), FORECAST_META["horizon_max"]))

    strength, slip, mirage = [], [], []
    for d in range(horizon + 1):
        strength.append(round(_strength_value(goal_days_in() + d, target), 2))
    slip = _slip_curve(start_val, horizon)
    mirage = _mirage_curve(start_val, horizon)

    return {
        "ok": True,
        "horizon": horizon,
        "start_value": start_val,
        "target_days": target,
        "days_in": goal_days_in(),
        "labels": [f"+{d}д" for d in range(horizon + 1)],
        "series": {
            "strength": strength,
            "slip": slip,
            "mirage": mirage,
        },
        "meta": FORECAST_META,
    }


def compute_risk():
    """Прозрачная эвристика вероятности срыва (0..100) с расшифровкой."""
    factors = []
    score = 0.0

    logs = BalanceLog.query.order_by(BalanceLog.day.desc()).limit(3).all()
    if logs:
        avg_index = sum((l.index or 0) for l in logs) / float(len(logs))
        delta = max(-40.0, min(40.0, -avg_index * 0.9))
        score += delta
        factors.append({
            "label": f"Средний индекс стабильности за 3 дня: {round(avg_index, 1)}",
            "impact": round(delta, 1),
        })
    else:
        score += 8
        factors.append({"label": "Нет телеметрии баланса за последние дни", "impact": 8.0})

    goal = get_life_goal()
    profile = get_profile()
    days_in = goal_days_in()
    if days_in <= 3:
        score += 18
        factors.append({"label": f"Серия всего {days_in} дн. — самый хрупкий период", "impact": 18.0})
    elif days_in >= 30:
        score -= 10
        factors.append({"label": f"Серия {days_in} дн. — привычка укрепляется", "impact": -10.0})

    recent_urges = UrgeLog.query.order_by(UrgeLog.id.desc()).limit(7).all()
    if recent_urges:
        losses = sum(1 for u in recent_urges if u.choice == "slip")
        pend = sum(1 for u in recent_urges if u.choice == "pending")
        d = losses * 12 + pend * 5
        score += d
        factors.append({
            "label": f"Из последних {len(recent_urges)} точек выбора: срывов {losses}, нерешённых {pend}",
            "impact": round(d, 1),
        })

    # физический контекст из последних КПТ-разборов
    last_cbt = CbtRecord.query.order_by(CbtRecord.id.desc()).limit(5).all()
    if last_cbt:
        bad_sleep = sum(1 for c in last_cbt if getattr(c, "bad_sleep", False))
        back = sum(1 for c in last_cbt if getattr(c, "back_pain", False))
        iso = sum(1 for c in last_cbt if getattr(c, "isolation", False))
        d = bad_sleep * 6 + back * 4 + iso * 5
        score += d
        if d:
            factors.append({
                "label": f"Телесный контекст (сон {bad_sleep}, спина {back}, одиночество {iso} из {len(last_cbt)})",
                "impact": round(d, 1),
            })

    if profile and (profile.slips_avoided or 0) > 0:
        d = -min(15.0, (profile.slips_avoided or 0) * 3.0)
        score += d
        factors.append({"label": f"Отбито атак: {profile.slips_avoided}", "impact": round(d, 1)})

    risk = int(max(0, min(100, round(50 + score))))
    if risk < 25:
        band = "низкий"
    elif risk < 50:
        band = "умеренный"
    elif risk < 75:
        band = "повышенный"
    else:
        band = "критический"

    return {"ok": True, "risk": risk, "band": band, "factors": factors}


def state_payload():
    profile = get_profile()
    board = get_board()
    marks = DayMark.query.all()
    logs = BalanceLog.query.order_by(BalanceLog.day.asc()).all()
    cbt = CbtRecord.query.order_by(CbtRecord.id.desc()).all()
    letters = Letter.query.order_by(Letter.id.desc()).all()
    workouts = WorkoutRecord.query.order_by(WorkoutRecord.id.desc()).all()
    goals = DailyGoal.query.filter_by(day=today_str()).all()
    steps = GoalStep.query.order_by(GoalStep.id.desc()).all()
    urges = UrgeLog.query.order_by(UrgeLog.id.desc()).limit(30).all()

    marks_dict = {}
    for m in marks:
        marks_dict[m.day] = {
            "status": m.status,
            "note": m.note or "",
            "slip_analysis": parse_slip_note(m.note),
        }

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
        "life_goal": life_goal_payload(),
        "goal_steps": [
            {"id": s.id, "text": s.text, "weight": s.weight or 1, "done": bool(s.done), "date": s.date}
            for s in steps
        ],
        "urge_logs": [
            {"id": u.id, "ts": u.ts, "day": u.day, "intensity": u.intensity,
             "trigger": u.trigger, "note": u.note, "choice": u.choice,
             "resolved_at": u.resolved_at, "days_at_stake": u.days_at_stake}
            for u in urges
        ],
        "marks": marks_dict,
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
                "bad_sleep": bool(getattr(c, "bad_sleep", False)),
                "back_pain": bool(getattr(c, "back_pain", False)),
                "isolation": bool(getattr(c, "isolation", False)),
            }
            for c in cbt
        ],
        "letters": [
            {"id": l.id, "title": l.title, "content": l.content, "date": l.date}
            for l in letters
        ],
        "workouts": [
            {"id": w.id, "workout_type": w.workout_type, "exercise_name": w.exercise_name,
             "reps_data": w.reps_data, "date": w.date}
            for w in workouts
        ],
        "daily_goals": [
            {"id": g.id, "text": g.text, "completed": bool(g.completed)}
            for g in goals
        ],
    }


# ==========================================
# МАРШРУТЫ
# ==========================================
@app.route("/")
@require_auth
def index():
    return render_template("index.html")


@app.route("/api/state")
@require_auth
def api_state():
    return jsonify(state_payload())


@app.route("/api/day-details", methods=["GET"])
@require_auth
def api_day_details():
    day = request.args.get("day", today_str())
    mark = DayMark.query.filter_by(day=day).first()
    log = BalanceLog.query.filter_by(day=day).first()
    goals = DailyGoal.query.filter_by(day=day).all()

    try:
        dt_obj = datetime.strptime(day, "%Y-%m-%d")
        d_ru_prefix = dt_obj.strftime("%d.%m.%Y")
    except ValueError:
        d_ru_prefix = day

    workouts = WorkoutRecord.query.filter(WorkoutRecord.date.like(f"%{d_ru_prefix}%")).all()

    slip_analysis = None
    if mark and mark.note:
        slip_analysis = parse_slip_note(mark.note)

    return jsonify({
        "ok": True,
        "day": day,
        "status": mark.status if mark else None,
        "note": mark.note if mark else "",
        "slip_analysis": slip_analysis,
        "balance": {
            "index": log.index if log else 0,
            "boosters": [k for k in (log.boosters_detail or "").split(",") if k] if log else [],
            "traps": [k for k in (log.traps_detail or "").split(",") if k] if log else [],
        },
        "goals": [{"id": g.id, "text": g.text, "completed": bool(g.completed)} for g in goals],
        "workouts": [{"workout_type": w.workout_type, "exercise_name": w.exercise_name, "reps_data": w.reps_data} for w in workouts],
    })


@app.route("/api/profile", methods=["POST"])
@require_auth
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
        db.session.add(Profile(name=name, days=days, slips_avoided=0, start_time=start_dt.isoformat()))
    db.session.commit()
    return jsonify(state_payload())


@app.route("/api/slip", methods=["POST"])
@require_auth
def api_slip():
    data = request.get_json(silent=True) or {}
    trigger = (data.get("trigger") or "").strip()
    feelings = (data.get("feelings") or "").strip()
    prevention = (data.get("prevention") or "").strip()
    note = json.dumps({"trigger": trigger, "feelings": feelings, "prevention": prevention}, ensure_ascii=False)
    apply_slip(note)
    db.session.commit()
    return jsonify(state_payload())


@app.route("/api/day/add", methods=["POST"])
@require_auth
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
@require_auth
def api_sos():
    profile = get_profile()
    if profile is not None:
        profile.slips_avoided = (profile.slips_avoided or 0) + 1
        db.session.commit()
    return jsonify(state_payload())


@app.route("/api/mark", methods=["POST"])
@require_auth
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
@require_auth
def api_balance():
    data = request.get_json(silent=True) or {}
    day = (data.get("day") or today_str()).strip()
    booster_keys = [str(v)[:32] for v in (data.get("boosters") or []) if str(v).strip()]
    trap_keys = [str(v)[:32] for v in (data.get("traps") or []) if str(v).strip()]

    index = 0
    for b in booster_keys:
        index += BOOSTER_WEIGHTS.get(b, 15)
    for t in trap_keys:
        index += TRAP_WEIGHTS.get(t, -15)

    log = BalanceLog.query.filter_by(day=day).first()
    if log is None:
        log = BalanceLog(day=day)
        db.session.add(log)
    log.boosters = len(booster_keys)
    log.traps = len(trap_keys)
    log.index = index
    log.boosters_detail = ",".join(booster_keys)[:255]
    log.traps_detail = ",".join(trap_keys)[:255]

    mark = DayMark.query.filter_by(day=day).first()
    if mark is None:
        mark = DayMark(day=day, note="")
        db.session.add(mark)
    if mark.status != "slip":
        mark.status = "win" if index >= -10 else "slip"

    db.session.commit()
    return jsonify(state_payload())


@app.route("/api/goals", methods=["POST"])
@require_auth
def api_goals_save():
    data = request.get_json(silent=True) or {}
    day = today_str()
    goals_list = data.get("goals", [])
    DailyGoal.query.filter_by(day=day).delete()
    for item in goals_list[:3]:
        text = str(item.get("text", "")).strip()[:255]
        if text:
            db.session.add(DailyGoal(day=day, text=text, completed=bool(item.get("completed", False))))
    db.session.commit()
    return jsonify(state_payload())


@app.route("/api/goal/toggle", methods=["POST"])
@require_auth
def api_goal_toggle():
    data = request.get_json(silent=True) or {}
    g_id = data.get("id")
    if g_id:
        goal = db.session.get(DailyGoal, g_id)
        if goal:
            goal.completed = not goal.completed
            db.session.commit()
    return jsonify(state_payload())


@app.route("/api/cbt", methods=["POST"])
@require_auth
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
            bad_sleep=bool(data.get("bad_sleep", False)),
            back_pain=bool(data.get("back_pain", False)),
            isolation=bool(data.get("isolation", False)),
        ))
        db.session.commit()
    return jsonify(state_payload())


@app.route("/api/cbt/import", methods=["POST"])
@require_auth
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
                bad_sleep=False, back_pain=False, isolation=False,
            ))
        db.session.commit()
    return jsonify(state_payload())


@app.route("/api/cbt/delete", methods=["POST"])
@require_auth
def api_cbt_delete():
    data = request.get_json(silent=True) or {}
    c_id = data.get("id")
    if c_id:
        rec = db.session.get(CbtRecord, c_id)
        if rec:
            db.session.delete(rec)
            db.session.commit()
    return jsonify(state_payload())


@app.route("/api/letter", methods=["POST"])
@require_auth
def api_letter():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:150]
    content = (data.get("content") or "").strip()
    if title and content:
        db.session.add(Letter(title=title, content=content, date=datetime.now().strftime("%d.%m.%Y %H:%M")))
        db.session.commit()
    return jsonify(state_payload())


@app.route("/api/workout", methods=["POST"])
@require_auth
def api_workout():
    data = request.get_json(silent=True) or {}
    w_type = (data.get("workout_type") or "").strip()[:100]
    ex_name = (data.get("exercise_name") or "").strip()[:150]
    reps = (data.get("reps_data") or "").strip()[:100]
    if w_type and ex_name and reps:
        db.session.add(WorkoutRecord(
            workout_type=w_type, exercise_name=ex_name, reps_data=reps,
            date=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ))
        db.session.commit()
    return jsonify(state_payload())


@app.route("/api/workout/delete", methods=["POST"])
@require_auth
def api_workout_delete():
    data = request.get_json(silent=True) or {}
    w_id = data.get("id")
    if w_id:
        rec = db.session.get(WorkoutRecord, w_id)
        if rec:
            db.session.delete(rec)
            db.session.commit()
    return jsonify(state_payload())


@app.route("/api/board", methods=["POST"])
@require_auth
def api_board():
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    board = get_board()
    board.content = content
    db.session.commit()
    return jsonify(state_payload())


# ---------- НОВОЕ: цель жизни и шаги ----------
@app.route("/api/life-goal", methods=["POST"])
@require_auth
def api_life_goal():
    data = request.get_json(silent=True) or {}
    goal = get_life_goal()
    if goal is None:
        goal = LifeGoal()
        db.session.add(goal)

    if "age" in data:
        try:
            goal.age = max(1, min(120, int(data.get("age") or 33)))
        except (TypeError, ValueError):
            goal.age = 33
    if "past_dependencies" in data:
        past = data.get("past_dependencies")
        if isinstance(past, str):
            past = [p.strip() for p in past.split(",") if p.strip()]
        if not isinstance(past, list):
            past = []
        goal.past_dependencies = json.dumps([str(p)[:80] for p in past][:20], ensure_ascii=False)
    if "current_dependency" in data:
        goal.current_dependency = (data.get("current_dependency") or "").strip()[:150]
    if "dependency_gives" in data:
        goal.dependency_gives = (data.get("dependency_gives") or "").strip()[:2000]
    if "goal_title" in data:
        goal.goal_title = (data.get("goal_title") or "").strip()[:200]
    if "goal_description" in data:
        goal.goal_description = (data.get("goal_description") or "").strip()[:4000]
    if "goal_days_target" in data:
        try:
            goal.goal_days_target = max(1, min(3650, int(data.get("goal_days_target") or 365)))
        except (TypeError, ValueError):
            goal.goal_days_target = 365
    if "started_at" in data and data.get("started_at"):
        goal.started_at = str(data.get("started_at"))[:100]
    elif not goal.started_at:
        # Первый раз создаём цель. Если человек уже в завязке (в онбординге указал
        # чистые дни), цель стартует с той же точки, а не с нуля. Иначе два счётчика
        # расходятся: таймер показывает 40 дней, а путь к цели — 0.
        profile = get_profile()
        inherited = None
        if profile and profile.start_time:
            try:
                candidate = datetime.fromisoformat(profile.start_time)
                if candidate <= datetime.now():
                    inherited = candidate.isoformat()
            except (ValueError, TypeError):
                inherited = None
        goal.started_at = inherited or datetime.now().isoformat()

    goal.updated_at = datetime.now().isoformat()
    db.session.commit()
    return jsonify(state_payload())


@app.route("/api/goal-step", methods=["POST"])
@require_auth
def api_goal_step():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()[:255]
    if text:
        try:
            weight = max(1, min(10, int(data.get("weight") or 1)))
        except (TypeError, ValueError):
            weight = 1
        db.session.add(GoalStep(
            text=text, weight=weight, done=False,
            date=datetime.now().strftime("%d.%m.%Y %H:%M"),
        ))
        db.session.commit()
    return jsonify(state_payload())


@app.route("/api/goal-step/toggle", methods=["POST"])
@require_auth
def api_goal_step_toggle():
    data = request.get_json(silent=True) or {}
    s_id = data.get("id")
    if s_id:
        step = db.session.get(GoalStep, s_id)
        if step:
            step.done = not step.done
            db.session.commit()
    return jsonify(state_payload())


@app.route("/api/goal-step/delete", methods=["POST"])
@require_auth
def api_goal_step_delete():
    data = request.get_json(silent=True) or {}
    s_id = data.get("id")
    if s_id:
        step = db.session.get(GoalStep, s_id)
        if step:
            db.session.delete(step)
            db.session.commit()
    return jsonify(state_payload())


# ---------- НОВОЕ: точка выбора (тяга) ----------
@app.route("/api/urge", methods=["POST"])
@require_auth
def api_urge():
    """Открыть точку выбора: оставляем запись pending с текущим стеком."""
    data = request.get_json(silent=True) or {}
    try:
        intensity = max(1, min(10, int(data.get("intensity") or 5)))
    except (TypeError, ValueError):
        intensity = 5

    now = datetime.now()
    urge = UrgeLog(
        ts=now.isoformat(),
        day=now.strftime("%Y-%m-%d"),
        intensity=intensity,
        trigger=(data.get("trigger") or "").strip()[:255],
        note=(data.get("note") or "").strip()[:2000],
        choice="pending",
        days_at_stake=goal_days_in(),
    )
    db.session.add(urge)
    db.session.commit()
    return jsonify({"ok": True, "urge_id": urge.id, "state": state_payload()})


@app.route("/api/urge/resolve", methods=["POST"])
@require_auth
def api_urge_resolve():
    """Разрешить точку выбора: strength (выстоял) или slip (сдался)."""
    data = request.get_json(silent=True) or {}
    u_id = data.get("id")
    choice = (data.get("choice") or "").strip()
    if choice not in ("strength", "slip"):
        return jsonify({"ok": False, "error": "choice должен быть strength или slip"}), 400

    urge = db.session.get(UrgeLog, u_id) if u_id else None
    if urge is None:
        urge = UrgeLog.query.filter_by(choice="pending").order_by(UrgeLog.id.desc()).first()
    if urge is None:
        return jsonify({"ok": False, "error": "Нет открытой точки выбора"}), 404

    urge.choice = choice
    urge.resolved_at = datetime.now().isoformat()

    if choice == "strength":
        profile = get_profile()
        if profile is not None:
            profile.slips_avoided = (profile.slips_avoided or 0) + 1
    else:
        note = json.dumps({
            "trigger": urge.trigger,
            "feelings": "Точка выбора: сдался",
            "prevention": (data.get("prevention") or "").strip(),
        }, ensure_ascii=False)
        apply_slip(note)

    db.session.commit()
    return jsonify({"ok": True, "choice": choice, "state": state_payload()})


@app.route("/api/urge/stats")
@require_auth
def api_urge_stats():
    urges = UrgeLog.query.order_by(UrgeLog.id.desc()).all()
    total = len(urges)
    wins = sum(1 for u in urges if u.choice == "strength")
    losses = sum(1 for u in urges if u.choice == "slip")
    pending = sum(1 for u in urges if u.choice == "pending")
    by_intensity = {}
    for u in urges:
        k = str(u.intensity)
        by_intensity.setdefault(k, {"total": 0, "wins": 0})
        by_intensity[k]["total"] += 1
        if u.choice == "strength":
            by_intensity[k]["wins"] += 1
    win_rate = round(100.0 * wins / total, 1) if total else 0.0
    return jsonify({"ok": True, "total": total, "wins": wins, "losses": losses,
                    "pending": pending, "win_rate": win_rate, "by_intensity": by_intensity})


@app.route("/api/forecast")
@require_auth
def api_forecast():
    try:
        horizon = int(request.args.get("horizon") or FORECAST_META["horizon_default"])
    except (TypeError, ValueError):
        horizon = FORECAST_META["horizon_default"]
    return jsonify(build_forecast(horizon=horizon))


@app.route("/api/risk")
@require_auth
def api_risk():
    return jsonify(compute_risk())


@app.route("/api/reset", methods=["POST"])
@require_auth
def api_reset():
    DayMark.query.delete()
    BalanceLog.query.delete()
    CbtRecord.query.delete()
    Letter.query.delete()
    WorkoutRecord.query.delete()
    StrategyBoard.query.delete()
    DailyGoal.query.delete()
    GoalStep.query.delete()
    UrgeLog.query.delete()
    LifeGoal.query.delete()
    Profile.query.delete()
    db.session.commit()
    return jsonify(state_payload())


@app.route("/export_cbt")
@require_auth
def export_cbt():
    records = CbtRecord.query.order_by(CbtRecord.id.desc()).all()
    text_data = "=== RECOVERY HUB: АРХИВ КПТ-РАЗБОРОВ ===\n\n"
    for r in records:
        text_data += f"📅 Дата: {r.date}\n🏷️ Категория: {r.category}\n🧠 Мысль: {r.automatic_thought}\n💡 Ответ: {r.rational_response}\n" + "-" * 50 + "\n\n"
    return Response(
        text_data,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-disposition": "attachment; filename=cbt_recovery_log.txt"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
