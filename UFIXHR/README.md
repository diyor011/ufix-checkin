# UFIX Check-in Bot

## Файлы
- `bot.py` — основной файл бота (aiogram)
- `attendance_bot.py` — логика посещаемости
- `config.py` — токен бота и admin ID
- `database.py` — работа с SQLite
- `attendance.db` — база данных

## Установка
```bash
pip install -r requirements.txt
```

## Настройка
Открой `config.py` и вставь свои данные:
```python
BOT_TOKEN = "ВАШ_ТОКЕН"
ADMIN_ID = ВАШ_TELEGRAM_ID
```

## Запуск
```bash
python bot.py
```
