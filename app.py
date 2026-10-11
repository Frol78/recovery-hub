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
# ТЕКСТЫ ДЛЯ СИМУЛЯТОРА РАЗВИЛКИ
# Правь формулировки здесь — фронт забирает их как есть.
# ==========================================
FORECAST_META = {
    "horizon_default": 30,
    "horizon_max": 180,
    "series": {
        "strength": {"label": "Путь силы", "desc": "Реальность, если ты выстоишь и не заплатишь зависимости"},
        "slip": {"label": "Путь срыва", "desc": "Реальность, если ты сдашься прямо сейчас"},
        "mirage": {"label": "Мираж зависимости", "desc": "То, что она тебе обещает в момент тяги"},
    },
    "slip_consequences": [
        {"icon": "📉", "title": "Дофаминовая яма",
         "text": "10 минут фантомного кайфа — и 3–5 дней серости. Ничего не радует: ни музыка, ни код, ни люди."},
        {"icon": "⚡", "title": "Сосуды и потенция",
         "text": "Хронический перегруз дофамином и сосудистый спазм бьют по эрекции. Это физиология, а не миф, и лечится она только воздержанием."},
        {"icon": "🧠", "title": "Укрепление старой связи",
         "text": "Каждый срыв протаптывает нейронную дорожку глубже. В следующий раз тянуть будет сильнее и быстрее."},
        {"icon": "⏳", "title": "Обнуление серии",
         "text": "Счётчик чистого времени уходит в ноль. Всё, что наработал днями и ночами, стирается за одну секунду."},
        {"icon": "🪞", "title": "Удар по самооценке",
         "text": "Стыд, торг, обесценивание себя. Ты снова тот, кто не держит слово даже самому себе."},
        {"icon": "🎯", "title": "Откат от целей",
         "text": "Девушка, целостность, сила духа — это не абстракция. Каждый срыв отодвигает всё это назад на дни и недели."},
    ],
    "strength_gains": [
        {"icon": "🛡️", "title": "Связь слабеет",
         "text": "Ты не заплатил зависимости. Дорожка сужается, а не расширяется — и в следующий раз тянуть будет тише."},
        {"icon": "🔥", "title": "Энергия остаётся в тебе",
         "text": "Тестостерон, дофаминовая чувствительность, ясность в голове — всё это остаётся в теле, а не сливается в унитаз."},
        {"icon": "🎯", "title": "+1 день к цели",
         "text": "Ты ближе к цели ровно на сутки. Сухие цифры, которые без пафоса складываются в новую жизнь."},
        {"icon": "🧱", "title": "Тренировка характера",
         "text": "Каждый пройденный шторм — это подход к штанге для воли. Ты становишься человеком, который держит слово."},
        {"icon": "🌈", "title": "Возврат красок",
         "text": "Реальность отдаёт обратно вкус: еда, музыка, работа, люди снова начинают цеплять по-настоящему."},
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
    date = db.Column(db.String(50), nullable=False)        # ISO timestamp
    day = db.Column(db.String(10), nullable=False, index=True)
    intensity = db.Column(db.Integer, default=5)           # 1..10
    trigger = db.Column(db.String(255), default="")
    note = db.Column(db.Text, default="")
    choice = db.Column(db.String(15), default="pending")   # pending / strength / slip
    resolved_at = db.Column(db.String(50), default="")
    days_at_stake = db.Column(db.Integer, default=0)       # сколько дней было на кону


def _ensure_column(table, column, ddl_type):
    """Безопасно добавляет колонку в существующую таблицу. Ничего не удаляет."""
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
            conn.commit()
    except Exception:
        pass


with app.app_context():
    db.create_all()
    # Авто-миграция старых баз: дописываем недостающие колонки, строки не трогаем
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


# ==========================================
# ПРОГНОЗНЫЙ ДВИЖОК (ТРИ КРИВЫЕ)
# ==========================================
def _strength_value(t, target):
    """Путь силы: плавный рост к 100 с насыщением."""
    if target <= 0:
        target = 365
    return 100.0 * (1.0 - math.exp(-2.4 * t / float(target)))


def _mirage_curve(start_val, horizon):
    """Мираж: мозг обещает подъём — реальность падает ниже всех."""
    floor = -45.0
    peak = start_val + 15.0
    out = []
    for d in range(horizon + 1):
        if d == 0:
            out.append(start_val)
        elif d == 1:
            out.appen
