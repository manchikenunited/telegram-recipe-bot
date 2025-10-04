import os
import json
from openai import OpenAI
from datetime import date, timedelta
from typing import List, Dict, Any

# --- ИНИЦИАЛИЗАЦИЯ OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = None
if OPENAI_API_KEY:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        print("✅ OpenAI Клиент успешно инициализирован.")
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось создать клиента OpenAI: {e}")
else:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: OPENAI_API_KEY не найден в переменных окружения.")


# --- ВАШИ ПЕРСОНАЛЬНЫЕ ДАННЫЕ ---
USER_KZHBU = {
    "me": "2204 ккал, 165г белка, 61г жиров, 248г углеводов.",
    "wife": "1703 ккал, 128г белка, 47г жиров, 192г углеводов.",
    
    # Целевая сумма и распределение калорий на двоих
    "total_target_kzhbu": "3907 Ккал, 293г Белка, 108г Жиров, 440г Углеводов",
    "target_distribution_kzhbu": {
        "Завтрак": "900-1100 ккал",
        "Обед": "1200-1400 ккал",
        "Перекус": "400-500 ккал",
        "Ужин": "1200-1400 ккал"
    }
}

# --- ОПРЕДЕЛЕНИЕ СТРУКТУРЫ ВЫВОДА (JSON Schema) ---
JSON_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "day": {"type": "string", "description": "День недели (например, Понедельник)"},
            "date": {"type": "string", "description": "Дата в формате YYYY-MM-DD"},
            "meals": {
                "type": "array",
                "description": "Список из 4 приемов пищи: Завтрак, Обед, Перекус, Ужин.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "description": "Тип приема пищи (строго: Завтрак, Обед, Перекус, Ужин)"},
                        "meal_name": {"type": "string", "description": "Краткое название блюда"},
                        "total_kzhbu_for_two": {"type": "string", "description": "Суммарное КЖБУ блюда для двух порций. Формат: 'Ккал: X, Б: Yг, Ж: Zг, У: Wг'."},
                        "weight_m": {"type": "integer", "description": "Рекомендуемый вес порции для мужчины в граммах (целое число)."},
                        "weight_w": {"type": "integer", "description": "Рекомендуемый вес порции для женщины в граммах (целое число)."},
                        "recipe_full": {"type": "string", "description": "Полный рецепт: ингредиенты (с указанием количества), шаги приготовления."}
                    },
                    "required": ["type", "meal_name", "total_kzhbu_for_two", "weight_m", "weight_w", "recipe_full"]
                }
            }
        },
        "required": ["day", "date", "meals"]
    }
}

# --- ФУНКЦИЯ СОЗДАНИЯ ПРОМПТА ---

def create_master_prompt(exclusion_list: List[str]) -> str:
    """Формирует детализированный промпт для OpenAI."""
    
    today = date.today()
    start_date = today + timedelta(days=(7 - today.weekday()))
    
    dates_list = []
    for i in range(5):
        current_date = start_date + timedelta(days=i)
        dates_list.append(current_date.strftime("%Y-%m-%d"))

    exclusions_text = ""
    if exclusion_list:
        print(f"🔎 Найдено {len(exclusion_list)} уникальных блюд для исключения за последние 21 дней.")
        exclusions_text = f"\nКРАЙНЕ ВАЖНО: Запрещено использовать следующие блюда из истории (последние 3 недели): {', '.join(exclusion_list)}"
    
    schema_string = json.dumps(JSON_SCHEMA, indent=2, ensure_ascii=False)
    
    prompt = f"""
    Ты - профессиональный шеф-повар и диетолог. Твоя задача — составить меню на 5 будних дней, деля дневную норму на 4 приема пищи: Завтрак, Обед, Перекус, Ужин.
    
    Дни для планирования (строго в формате YYYY-MM-DD): {dates_list}
    
    Целевые суточные нормы КЖБУ:
    - Мужчина: {USER_KZHBU['me']}
    - Женщина: {USER_KZHBU['wife']}
    
    ЧРЕЗВЫЧАЙНО ВАЖНЫЕ УКАЗАНИЯ ПО КЖБУ:
    1. ОБЩАЯ ЦЕЛЬ СУММАРНОЙ КАЛОРИЙНОСТИ НА ДВОИХ: **{USER_KZHBU['total_target_kzhbu']}**.
    2. КАЛОРИЙНОСТЬ КАЖДОГО БЛЮДА (СУММАРНО НА ДВОИХ) ДОЛЖНА БЫТЬ В СЛЕДУЮЩИХ ПРИМЕРНЫХ ДИАПАЗОНАХ:
       - Завтрак: **{USER_KZHBU['target_distribution_kzhbu']['Завтрак']}**
       - Обед: **{USER_KZHBU['target_distribution_kzhbu']['Обед']}**
       - Перекус: **{USER_KZHBU['target_distribution_kzhbu']['Перекус']}**
       - Ужин: **{USER_KZHBU['target_distribution_kzhbu']['Ужин']}**
       
    КРАЙНЕ ВАЖНО:
    1. Сначала составь **реалистичный полный рецепт**, затем **РАССЧИТАЙ** КЖБУ на основе ингредиентов рецепта. Не придумывай цифры.
    2. **Вес порций (weight_m, weight_w) должен быть реалистичным** для готового блюда. **200 грамм каши не могут быть 900 Ккал!** Калорийность должна следовать за реалистичным объемом порции и составом рецепта.
    3. Суммарная дневная калорийность **ВСЕХ 4-х блюд** должна максимально точно соответствовать общей целевой сумме **3907 Ккал**. Отклонение не должно превышать 100 ккал.
    4. Распредели дневную норму КЖБУ (для мужчины и женщины) между 4 приемами пищи, стараясь максимально приблизиться к их индивидуальным целям.
    5. ПОЛЕ 'total_kzhbu_for_two' ДОЛЖНО СОДЕРЖАТЬ СТРОКУ С РАСЧЕТОМ (Ккал, Б, Ж, У) И НЕ ДОЛЖНО БЫТЬ ПУСТЫМ. Используй формат: 'Ккал: X, Б: Yг, Ж: Zг, У: Wг'.
    6. Рассчитай **рекомендуемый вес порции в граммах (целое число)** отдельно для мужчины (weight_m) и для женщины (weight_w).
    7. Рецепты должны быть реалистичными (не более 60 минут готовки).
    {exclusions_text}
    
    Верни результат СТРОГО в формате JSON, соответствующем предоставленной СХЕМЕ:
    {schema_string}
    """
    return prompt

# --- ГЛАВНАЯ ФУНКЦИЯ ВЫЗОВА API ---

def generate_weekly_plan(exclusion_list: List[str]) -> List[Dict[str, Any]] | None:
    """
    Отправляет запрос в OpenAI и возвращает готовый список планов.
    """
    if client is None:
        print("❌ Генерация невозможна: Клиент OpenAI не инициализирован.")
        return None
        
    prompt = create_master_prompt(exclusion_list)
    print("--- 1. Запрос в OpenAI: Начинаем отправку. ---")
    
    try:
        response = client.chat.completions.create(
            # Используем gpt-4o-mini для скорости. Если проблема сохранится, перейдем на gpt-4o.
            model="gpt-4o-mini", 
            response_format={"type": "json_object"}, 
            messages=[
                {"role": "system", "content": "Ты - система, которая генерирует JSON-объекты со списком рецептов. Твой ответ должен быть только JSON, без комментариев. Используй СХЕМУ, предоставленную в запросе."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7 
        )

        print("--- 2. Запрос в OpenAI: Ответ получен! ---")
        
        json_content = response.choices[0].message.content.strip()
        plan_data = json.loads(json_content)
        
        print("✅ План успешно сгенерирован и разобран.")
        return plan_data

    except json.JSONDecodeError as e:
        print(f"❌ ОШИБКА ПАРСИНГА JSON: ИИ не смог вернуть чистый JSON. Ошибка: {e}")
        return None
    except Exception as e:
        print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ВЫЗОВА OpenAI (Сетевая/API): {e}")
        return None

# --- ТЕСТОВЫЙ ЗАПУСК ---
if __name__ == '__main__':
    print("--- Тестовый запуск ai_generator.py ---")
    test_exclusions = ["Омлет", "Плов"]
    plan = generate_weekly_plan(test_exclusions)
    
    if plan:
        print(f"\nСгенерировано {len(plan)} дней. Первый день: {plan[0]['day']}.")
    else:
        print("Генерация тестового плана не удалась.")
