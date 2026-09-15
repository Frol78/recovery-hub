# Что изменилось: данные переехали на сервер

Раньше всё лежало в localStorage браузера — поэтому на телефоне прогресс был пустой.
Теперь состояние живёт в `recovery.db` на сервере, а браузер только рисует то, что получил.

## Файлы

| Файл | Что делает |
|---|---|
| `app.py` | Flask + SQLite. Модели Profile / DayMark / BalanceLog / CbtRecord, JSON API |
| `templates/index.html` | Интерфейс. Ни одного localStorage — только запросы к API |
| `amvera.yml` | `persistenceMount: /data` — постоянный диск для базы |
| `requirements.txt` | Flask, Flask-SQLAlchemy, gunicorn |

## Схема хранения

```
recovery.db  (на постоянном диске /data)
├── profile       — позывной, дни, отбитые атаки, время старта
├── day_mark      — календарь: дата + статус (win/slip) + заметка
├── balance_log   — баланс дня: бустеры, ловушки, индекс
└── cbt_record    — разборы автоматических мыслей
```

## API

| Метод | Роут | Назначение |
|---|---|---|
| GET | `/api/state` | полный слепок состояния (профиль, отметки, баланс, КПТ) |
| POST | `/api/profile` | создать/обновить профиль |
| POST | `/api/day/add` | +1 день, заодно ставит сегодня «победа» |
| POST | `/api/sos` | +1 к отбитым атакам |
| POST | `/api/mark` | отметить день: `{day, status: win\|slip\|null, note}` |
| POST | `/api/balance` | баланс дня: `{day, boosters: [...], traps: [...]}` |
| POST | `/api/cbt` | добавить КПТ-разбор |
| POST | `/api/reset` | удалить все данные |
| GET | `/export_cbt` | выгрузка КПТ-архива в TXT |

Любой POST возвращает свежий слепок — клиент сразу перерисовывается, ничего не кэширует.

## Деплой

```bash
git rm --cached recovery.db          # старая база уходит из репозитория
echo "recovery.db" >> .gitignore
printf "*.db\n__pycache__/\n" >> .gitignore

git add app.py templates/index.html amvera.yml requirements.txt .gitignore
git commit -m "Данные переехали на сервер: постоянный диск, JSON API, кросс-девайс"
git push origin main
```

В панели Amvera: **Конфигурация → постоянное хранилище**, том `/data`.
Бейдж в шапке приложения покажет `● защищено`, когда диск подключён.

## Перенос старых записей

Старые данные были в localStorage — сервер о них не знает. Открой сайт в том же
браузере, где есть история, нажми F12 → Console и выполни:

```javascript
copy(JSON.stringify(JSON.parse(localStorage.getItem('recovery_hub_data')), null, 2))
```

Скопированный JSON покажет, какие дни и КПТ-записи нужно внести заново.
Объём — несколько дней, вручную быстрее, чем писать миграцию.
