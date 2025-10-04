import os
import datetime
import asyncio
import traceback
from dotenv import load_dotenv

# --- 1. КРИТИЧЕСКАЯ ЗАГРУЗКА КЛЮЧЕЙ ---
load_dotenv() 

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUR_CHAT_ID = os.getenv("YOUR_CHAT_ID")

if YOUR_CHAT_ID:
    try:
        YOUR_CHAT_ID = int(YOUR_CHAT_ID)
    except ValueError:
        print("❌ ОШИБКА: YOUR_CHAT_ID в .env должен быть числом.")
        YOUR_CHAT_ID = None

# --- ИМПОРТЫ ЛОГИКИ И БИБЛИОТЕК ---
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
# APScheduler импортируем, но не используем, пока не будет включена автоматизация
from apscheduler.schedulers.background import BackgroundScheduler 
from apscheduler.triggers.cron import CronTrigger

# Ваша логика:
from db_manager import init_db, get_exclusion_list, save_recipes, Recipe, Session
from ai_generator import generate_weekly_plan 


# --- 2. ГЛАВНЫЕ ФУНКЦИИ БОТА (АСИНХРОННЫЕ) ---

def sync_generation_logic():
    """
    Синхронная функция для блокирующих операций: Чтение БД, вызов AI, запись в БД.
    Запускается в отдельном потоке (executor).
    """
    try:
        # 1. Получаем список исключений
        exclusion_list = get_exclusion_list(days=21)
        
        # 2. Генерируем план (блокирующий вызов)
        weekly_plan_json = generate_weekly_plan(exclusion_list) 
        
        if not weekly_plan_json:
            return None, "❌ Ошибка генерации: ИИ не смог создать план. Проверьте логи консоли."

        # --- КОРРЕКТИРУЕМ ФОРМАТ JSON ОТ ИИ (УНИВЕРСАЛЬНАЯ ПРОВЕРКА) ---
        if isinstance(weekly_plan_json, dict):
            extracted_list = None
            for key in ['plan', 'plans', 'weekly_plan', 'menu', 'recipes']:
                if key in weekly_plan_json and isinstance(weekly_plan_json[key], list):
                    extracted_list = weekly_plan_json[key]
                    print(f"✅ Успешно извлечен список из словаря по стандартному ключу: '{key}'.")
                    break
            
            if extracted_list is None:
                for value in weekly_plan_json.values():
                    if isinstance(value, list):
                        extracted_list = value
                        print("✅ Успешно извлечен список из словаря по универсальному поиску.")
                        break

            if extracted_list is not None:
                weekly_plan_json = extracted_list
            else:
                print(f"❌ Ошибка формата: ИИ вернул словарь, но список дней не найден внутри.")
                return None, "❌ Ошибка формата JSON: ИИ вернул неверный словарь. Проверьте консоль."
        
        if not isinstance(weekly_plan_json, list):
            print(f"❌ ФИНАЛЬНАЯ ОШИБКА формата: Ожидался список, но получен тип {type(weekly_plan_json)}")
            return None, "❌ ФИНАЛЬНАЯ ОШИБКА формата JSON: Ожидался список. Проверьте консоль."
            
        # --- СОХРАНЕНИЕ В БД И ФОРМАТИРОВАНИЕ ---
        recipes_to_save = []
        telegram_message = "✨ **Ваш план питания на 5 дней готов!** ✨\n\n"
        
        for day_plan in weekly_plan_json:
            
            if not isinstance(day_plan, dict):
                 print(f"❌ Ошибка в структуре: Элемент '{day_plan}' в списке не является словарем.")
                 continue 

            try:
                # 1. Форматирование заголовка дня
                telegram_message += f"🗓️ **{day_plan['day']}** ({day_plan['date']}):\n"
                meal_date_obj = datetime.datetime.strptime(day_plan['date'], "%Y-%m-%d").date()

                for meal in day_plan['meals']:
                    
                    # --- ИЗВЛЕЧЕНИЕ С БЕЗОПАСНЫМИ ЗНАЧЕНИЯМИ ПО УМОЛЧАНИЮ (.get()) ---
                    kzhbu_info = meal.get('total_kzhbu_for_two', 'КЖБУ: Расчет отсутствует ❌').strip()
                    weight_m = meal.get('weight_m', 'N/A')
                    weight_w = meal.get('weight_w', 'N/A')
                    meal_type = meal.get('type', 'Прием пищи')
                    meal_name = meal.get('meal_name', 'Неизвестное блюдо')
                    recipe_full = meal.get('recipe_full', 'Нет полного рецепта')
                    
                    if not kzhbu_info or kzhbu_info == 'N/A':
                        kzhbu_info = "КЖБУ: Расчет отсутствует ❌"
                    
                    # 2. Формируем подробный рецепт для сохранения в DB
                    full_recipe_text = (
                        f"**Суммарное КЖБУ (на двоих):** {kzhbu_info}\n\n"
                        f"**--- РЕЦЕПТ ---**\n"
                        f"{recipe_full}"
                    )
                    
                    # 3. Формируем строку для Telegram-сообщения
                    meal_line = (
                        f"   - **{meal_type}:** {meal_name}\n"
                        f"     (Суммарное КЖБУ: {kzhbu_info})\n" 
                        f"     _Порции:_ (М: {weight_m}г, Ж: {weight_w}г)\n" 
                    )
                    telegram_message += meal_line
                    # -------------------------------------------------------------------
                    
                    # 4. Сохраняем в список для БД
                    recipes_to_save.append({
                        'meal_date': meal_date_obj,
                        'meal_name': meal_name,
                        'recipe_full': full_recipe_text 
                    })
                
                telegram_message += "\n"
                
            except KeyError as e:
                print(f"❌ Критическая ошибка в ключах JSON: Отсутствует основной ключ {e} (day, date, meals) в элементе дня/блюда.")
                continue 

        # Сохранение (синхронный вызов)
        save_recipes(recipes_to_save)
        
        return telegram_message, None

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ВНУТРЕННЕЙ ЛОГИКИ:\n{error_trace}")
        return None, f"❌ КРИТИЧЕСКАЯ ОШИБКА: Произошел сбой при генерации или сохранении. См. консоль."


async def generate_and_send_weekly(context: ContextTypes.DEFAULT_TYPE):
    """
    Асинхронный вызов, который запускает синхронную логику в отдельном потоке.
    """
    print("--- 🚀 АСИНХРОННЫЙ ВЫЗОВ: Запуск еженедельной генерации. ---")

    loop = asyncio.get_running_loop() 
    
    telegram_message, error_message = await loop.run_in_executor(
        None, 
        sync_generation_logic
    )

    final_text = telegram_message if telegram_message else error_message
    parse_mode = 'Markdown' if telegram_message else None
    
    if YOUR_CHAT_ID:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID, 
            text=final_text, 
            parse_mode=parse_mode
        )
    print("--- Генерация завершена. ---")


async def send_daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет меню на текущий день и детали. Используется также командой /today.
    """
    current_date = datetime.date.today() 
    print(f"--- ⏰ Запрос меню на {current_date}. ---")

    def sync_get_recipes():
        session = Session()
        try:
            today_recipes = session.query(Recipe).filter(
                Recipe.meal_date == current_date
            ).all()
            return today_recipes
        finally:
            session.close()

    loop = asyncio.get_running_loop()
    today_recipes = await loop.run_in_executor(None, sync_get_recipes)


    if not today_recipes and YOUR_CHAT_ID:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=f"🤔 На сегодня ({current_date.strftime('%d.%m.%Y')}) меню не найдено. Воспользуйтесь /generate_test."
        )
        return

    # 2. Форматирование сообщения 
    reminder_message = f"🔔 **Ваше меню на сегодня, {current_date.strftime('%d.%m.%Y')}!** 🔔\n\n"
    
    for recipe in today_recipes:
        reminder_message += f"🍽️ **{recipe.meal_name}**\n\n"
        reminder_message += f"{recipe.recipe_full}\n\n---\n\n" 
        
    if YOUR_CHAT_ID:
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=reminder_message,
            parse_mode='Markdown'
        )
    print(f"--- Ежедневное уведомление на {current_date} отправлено. ---")


# --- 3. КОМАНДЫ TELEGRAM ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start."""
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Я бот-планировщик рецептов.\n"
        f"ID чата для уведомлений: **{YOUR_CHAT_ID}**.\n"
        f"Доступные команды: /generate_test, /today, /clear_history."
    )

async def generate_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /generate_test для немедленного запуска генерации."""
    if not YOUR_CHAT_ID or str(update.effective_chat.id) != str(YOUR_CHAT_ID):
        await update.message.reply_text("Эта команда доступна только администратору и только в его чате.")
        return

    await update.message.reply_text("🚀 Запускаю немедленную генерацию меню (это может занять до 20 секунд)...")

    await generate_and_send_weekly(context)
    
    await update.message.reply_text("✅ Запрос на генерацию отправлен. Проверьте сообщения.")


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /today для немедленной отправки меню на текущий день."""
    if not YOUR_CHAT_ID or str(update.effective_chat.id) != str(YOUR_CHAT_ID):
        await update.message.reply_text("Эта команда доступна только администратору и только в его чате.")
        return

    await update.message.reply_text("🔎 Ищу и отправляю меню на сегодня...")
    await send_daily_reminder(context)
    
    
def sync_clear_history_logic():
    """Синхронная логика для очистки таблицы Recipe."""
    session = Session()
    try:
        num_deleted = session.query(Recipe).delete()
        session.commit()
        return f"✅ Успешно удалено {num_deleted} записей из истории рецептов. История исключений сброшена!"
    except Exception as e:
        session.rollback()
        return f"❌ Ошибка при очистке базы данных: {e}"
    finally:
        session.close()


async def clear_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /clear_history для очистки базы данных рецептов."""
    if not YOUR_CHAT_ID or str(update.effective_chat.id) != str(YOUR_CHAT_ID):
        await update.message.reply_text("Эта команда доступна только администратору и только в его чате.")
        return

    await update.message.reply_text("🗑️ Запускаю очистку истории рецептов (может занять несколько секунд)...")
    
    loop = asyncio.get_running_loop()
    result_message = await loop.run_in_executor(
        None, 
        sync_clear_history_logic
    )
    
    await update.message.reply_text(result_message)


# --- 4. ОСНОВНАЯ СИНХРОННАЯ ФУНКЦИЯ ЗАПУСКА ---

def main() -> None:
    """Инициализирует БД, запускает планировщик и бота."""
    
    if not TELEGRAM_TOKEN or not YOUR_CHAT_ID:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: Токен Telegram или ID чата не найден/некорректен.")
        return

    init_db() 
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # --- БЛОК ПЛАНИРОВЩИКА (ЗАКОММЕНТИРОВАН ДЛЯ РУЧНОГО ТЕСТИРОВАНИЯ) ---
    # scheduler = BackgroundScheduler()
    # 
    # # Генерация: Воскресенье, 10:00
    # scheduler.add_job(
    #     generate_and_send_weekly, 
    #     trigger=CronTrigger(day_of_week='sun', hour='10', minute='0'),
    #     id='weekly_generation',
    #     name='Weekly Recipe Generation',
    #     args=[application] 
    # )
    # 
    # # Напоминание: Будни, 07:00
    # scheduler.add_job(
    #     send_daily_reminder, 
    #     trigger=CronTrigger(day_of_week='mon-fri', hour='7', minute='0'),
    #     id='daily_reminder',
    #     name='Daily Meal Reminder',
    #     args=[application] 
    # )
    # 
    # scheduler.start()
    # print("Планировщик запущен. Задания установлены.")
    # ----------------------------------------------------------------------

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("generate_test", generate_test_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("clear_history", clear_history_command))
    
    print("Бот запущен и прослушивает команды...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем.")
    except Exception as e:
        print(f"\nКритическая ошибка запуска: {e}")
