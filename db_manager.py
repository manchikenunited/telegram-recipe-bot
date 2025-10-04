import datetime
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# --- 1. ОПРЕДЕЛЕНИЕ БАЗЫ ---
# Базовый класс для объявления моделей
Base = declarative_base()

# Имя файла базы данных SQLite. Этот файл будет создан автоматически.
DATABASE_FILE = "recipes.db"
# Создаем движок SQLAlchemy для SQLite
engine = create_engine(f"sqlite:///{DATABASE_FILE}")
# Создаем класс сессий, через который мы будем общаться с БД
Session = sessionmaker(bind=engine)

# --- 2. МОДЕЛЬ ДАННЫХ (ТАБЛИЦА 'recipes_history') ---
class Recipe(Base):
    """Модель для хранения истории сгенерированных блюд."""
    __tablename__ = 'recipes_history'

    id = Column(Integer, primary_key=True)
    # Дата потребления блюда (обязательное поле)
    meal_date = Column(Date, nullable=False)
    # Название блюда (для проверки на повторы, обязательное поле)
    meal_name = Column(String, nullable=False)
    # Полный текст рецепта (ингредиенты, шаги, КЖБУ)
    recipe_full = Column(String)
    # Дата и время, когда запись была добавлена в базу
    generated_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Recipe(meal_name='{self.meal_name}', meal_date='{self.meal_date}')>"

# --- 3. ФУНКЦИИ УПРАВЛЕНИЯ БД ---

def init_db():
    """Создает базу данных и таблицу, если они не существуют."""
    try:
        # Создает все таблицы, определенные через Base (в нашем случае - Recipe)
        Base.metadata.create_all(engine)
        print(f"База данных {DATABASE_FILE} и таблица 'recipes_history' инициализированы.")
    except Exception as e:
        print(f"Критическая ошибка при инициализации БД: {e}")

def save_recipes(recipes_data: list):
    """
    Сохраняет список рецептов в базу данных.
    Ожидает список словарей, где каждый словарь содержит: 
    'meal_date' (объект datetime.date), 'meal_name' (str), 'recipe_full' (str).
    """
    session = Session()
    try:
        new_recipes = []
        for data in recipes_data:
            recipe = Recipe(
                meal_date=data['meal_date'],
                meal_name=data['meal_name'],
                recipe_full=data['recipe_full']
            )
            new_recipes.append(recipe)
        
        session.add_all(new_recipes)
        session.commit()
        print(f"✅ Успешно сохранено {len(new_recipes)} новых рецептов.")
        return True
    except Exception as e:
        session.rollback()
        print(f"❌ Ошибка при сохранении рецептов: {e}")
        return False
    finally:
        session.close()

def get_exclusion_list(days: int = 21) -> list[str]:
    """
    Возвращает список уникальных названий блюд, запланированных
    за последние 'days' дней, для использования в качестве исключений для ИИ.
    """
    session = Session()
    try:
        # Вычисляем дату, которая была 21 день назад (или days дней назад)
        start_date = datetime.date.today() - datetime.timedelta(days=days)
        
        # Выбираем уникальные названия блюд, запланированных с этой даты
        exclusion_list = session.query(Recipe.meal_name).filter(
            Recipe.meal_date >= start_date
        ).distinct().all()
        
        # Преобразуем результат из списка кортежей в простой список строк
        result = [item[0] for item in exclusion_list]
        
        print(f"🔎 Найдено {len(result)} уникальных блюд для исключения за последние {days} дней.")
        return result
    except Exception as e:
        print(f"❌ Ошибка при получении списка исключений: {e}")
        return []
    finally:
        session.close()

# Тестовый запуск: если вы запустите этот файл напрямую, он создаст базу и проверит функции.
if __name__ == '__main__':
    from datetime import date
    
    print("--- Тест БД ---")
    init_db()
    
    # 1. Тест сохранения: сохраним завтрашнее и послезавтрашнее блюда
    test_data = [
        {'meal_date': date.today() + datetime.timedelta(days=1), 'meal_name': 'Омлет со шпинатом', 'recipe_full': '...'},
        {'meal_date': date.today() + datetime.timedelta(days=2), 'meal_name': 'Курица в соусе терияки', 'recipe_full': '...'},
    ]
    save_recipes(test_data)
    
    # 2. Тест списка исключений
    exclusions = get_exclusion_list(days=3)
    print("\nПолученный список исключений:", exclusions)
