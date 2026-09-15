import os
import random
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, Response
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)


basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'recovery.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Модель профиля
class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    days = db.Column(db.Integer, default=0)
    slips_avoided = db.Column(db.Integer, default=0)
    start_time = db.Column(db.String(100), nullable=True) # Точное время старта в ISO формате

# Модель для КПТ-дневника
class CbtRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False)
    automatic_thought = db.Column(db.Text, nullable=False)
    rational_response = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(50), nullable=False)

with app.app_context():
    db.create_all()
print("✅ База данных создана!")
print("Путь к базе:", os.path.join(basedir, 'recovery.db'))
print("Файл существует:", os.path.exists(os.path.join(basedir, 'recovery.db')))
SOS_TIPS = [
    {"title": "🚨 Тревога!", "text": "Братан, стоп! Руки убрали от клавиатуры. Это просто ловушка дофамина. Иди сделай 20 отжиманий или холодный душ."},
    {"title": "🧠 Режим зомби", "text": "Мозг сейчас пытается тебя обмануть ради легкого дофамина. Не ведись на этот развод, ты сильнее."},
    {"title": "⚡ Перезагрузка", "text": "Слей энергию в реальное дело, а не в унитаз. Встань, пройдись по комнате, выпей стакан воды."},
    {"title": "🛡️ Жесткий контроль", "text": "Вспомни, ради чего ты начал. Эта минутная слабость стоит твоих дней прогресса? Точно нет."}
]

def get_status(days):
    if days <= 3:
        return {"name": "🧟‍♂️ Зомби-режим", "desc": "Осторожно, мозг требует дофаминовую иглу. Самый опасный период."}
    elif days <= 10:
        return {"name": "🔥 Ломка и бунт", "desc": "Сила воли включена на максимум. Держись зубами, дальше станет полегче."}
    elif days <= 30:
        return {"name": "🛡️ Первые победы", "desc": "Нервная система начинает оживать. Энергия возвращается в тело."}
    elif days <= 90:
        return {"name": "⚡ Набор массы", "desc": "Tяга отступает. Появляется фокус, ресурс и драйв жить."}
    else:
        return {"name": "👑 Альфа-состояние", "desc": "Легендарный уровень. Либидо, энергия и контроль над своей жизнью полностью твои."}

@app.route("/")
def index():
    profile = Profile.query.first()
    status = None
    cbt_records = []
    if profile:
        status = get_status(profile.days)
        cbt_records = CbtRecord.query.order_by(CbtRecord.id.desc()).all()
        
    return render_template("index.html", profile=profile, status=status, cbt_records=cbt_records)

@app.route("/create", methods=["POST"])
def create():
    name = request.form.get("name", "Боец")
    days = int(request.form.get("days", 0))
    
    # ИСПРАВЛЕНИЕ: Больше не удаляем базу! Проверяем, есть ли уже профиль.
    profile = Profile.query.first()
    start_dt = datetime.now() - timedelta(days=days)
    
    if profile:
        # Если профиль уже есть — просто обновляем данные, не трогая историю КПТ
        profile.name = name
        profile.days = days
        profile.start_time = start_dt.isoformat()
    else:
        # Если профиля не было — создаем новый
        new_profile = Profile(
            name=name, 
            days=days, 
            slips_avoided=0,
            start_time=start_dt.isoformat()
        )
        db.session.add(new_profile)
        
    db.session.commit()
    return redirect(url_for("index"))

@app.route("/update", methods=["POST"])
def update():
    profile = Profile.query.first()
    if profile:
        add_days = int(request.form.get("add_days", 1))
        profile.days += add_days
        db.session.commit()
    return redirect(url_for("index"))

@app.route("/add_cbt", methods=["POST"])
def add_cbt():
    category = request.form.get("category", "Общее")
    automatic_thought = request.form.get("automatic_thought", "")
    rational_response = request.form.get("rational_response", "")
    current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    if automatic_thought and rational_response:
        new_record = CbtRecord(
            category=category,
            automatic_thought=automatic_thought,
            rational_response=rational_response,
            date=current_date
        )
        db.session.add(new_record)
        db.session.commit()
        
    return redirect(url_for("index"))

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
        mimetype="text/plain",
        headers={"Content-disposition": "attachment; filename=cbt_recovery_log.txt"}
    )

@app.route("/sos")
def sos():
    profile = Profile.query.first()
    if profile:
        profile.slips_avoided += 1
        db.session.commit()
    
    tip = random.choice(SOS_TIPS)
    return render_template("sos.html", tip=tip, profile=profile)

@app.route("/reset", methods=["POST"])
def reset():
    # Полный сброс теперь доступен ТОЛЬКО через специальную кнопку сброса кластера внизу страницы
    Profile.query.delete()
    CbtRecord.query.delete()
    db.session.commit()
    return redirect(url_for("index"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
