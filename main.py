# -*- coding: utf-8 -*-
"""
Основной файл телеграм-бота для записи к парикмахеру.
"""
import asyncio
import logging
import datetime
import json
from typing import Dict, List, Optional, Union, Any

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    CallbackQuery
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

from config import (
    BOT_TOKEN, 
    SERVICES, 
    MASTER_TELEGRAM_ID, 
    APPOINTMENT_STATUSES,
    BARBERSHOP_ADDRESS
)
from database import (
    create_tables, 
    add_user, 
    get_user, 
    get_user_appointments,
    create_appointment, 
    get_appointment_by_id,
    get_appointment_with_user,
    update_appointment_status,
    cancel_appointment
)
from services import (
    calculate_total_duration, 
    validate_services,
    get_available_slots, 
    format_time_slot, 
    format_appointment_info,
    is_valid_date
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(
    MAIN_MENU,
    SELECTING_SERVICES,
    SELECTING_DATE,
    SELECTING_TIME,
    CONFIRMING_APPOINTMENT,
    VIEWING_APPOINTMENTS,
    ADMIN_MENU,
) = range(7)

# Callback данные для InlineKeyboardButton
CALLBACK_SERVICES_PREFIX = "service:"
CALLBACK_DATE_PREFIX = "date:"
CALLBACK_TIME_PREFIX = "time:"
CALLBACK_APPOINTMENT_PREFIX = "appointment:"
CALLBACK_CONFIRM_PREFIX = "confirm:"
CALLBACK_CANCEL_PREFIX = "cancel:"
CALLBACK_ADMIN_CONFIRM = "admin_confirm:"
CALLBACK_ADMIN_CANCEL = "admin_cancel:"
CALLBACK_ADMIN_LIST = "admin_list:"
CALLBACK_ADMIN_DATE = "admin_date:"
CALLBACK_ADMIN_STATUS = "admin_status:"

# Данные пользовательской сессии
user_data_dict = {}


def get_user_data(user_id: int) -> Dict:
    """
    Получает данные пользовательской сессии.
    
    Args:
        user_id (int): ID пользователя в Telegram
        
    Returns:
        Dict: Словарь с данными пользователя
    """
    if user_id not in user_data_dict:
        user_data_dict[user_id] = {
            "selected_services": [],
            "selected_date": None,
            "selected_time": None,
        }
    return user_data_dict[user_id]


def clear_user_data(user_id: int) -> None:
    """
    Очищает данные пользовательской сессии.
    
    Args:
        user_id (int): ID пользователя в Telegram
    """
    if user_id in user_data_dict:
        user_data_dict[user_id] = {
            "selected_services": [],
            "selected_date": None,
            "selected_time": None,
        }


# Функции для создания клавиатур
def get_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру главного меню.
    
    Args:
        is_admin (bool): Является ли пользователь администратором
        
    Returns:
        ReplyKeyboardMarkup: Клавиатура с кнопками выбора услуги и просмотра записей
    """
    keyboard = [
        ["✅ Старт"],
        ["Выбрать услугу"],
        ["Мои записи"]
    ]
    
    # Добавляем кнопку админ-панели для администратора
    if is_admin:
        keyboard.append(["👨‍💼 Админ-панель"])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_services_keyboard(selected_services: List[str]) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для выбора услуг.
    
    Args:
        selected_services (List[str]): Список уже выбранных услуг
        
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с услугами и кнопкой "Готово"
    """
    keyboard = []
    
    # Добавляем по 2 услуги в ряд
    services_list = list(SERVICES.keys())
    for i in range(0, len(services_list), 2):
        row = []
        for service_name in services_list[i:i+2]:
            # Отмечаем выбранные услуги
            prefix = "✅ " if service_name in selected_services else ""
            row.append(InlineKeyboardButton(
                f"{prefix}{service_name} ({SERVICES[service_name]} мин)",
                callback_data=f"{CALLBACK_SERVICES_PREFIX}{service_name}"
            ))
        keyboard.append(row)
    
    # Добавляем кнопку "Готово", если выбрана хотя бы одна услуга
    if selected_services:
        total_duration = calculate_total_duration(selected_services)
        keyboard.append([
            InlineKeyboardButton(
                f"Готово (всего {total_duration} мин)",
                callback_data="services_done"
            )
        ])
    
    # Добавляем кнопку "Отмена"
    keyboard.append([
        InlineKeyboardButton("Отмена", callback_data="cancel")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_date_keyboard() -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для выбора даты.
    
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с датами на ближайшие 7 дней
    """
    keyboard = []
    today = datetime.date.today()
    
    # Создаем кнопки с датами на ближайшие 7 дней
    for i in range(7):
        date = today + datetime.timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        
        # Форматируем название дня недели
        weekday_names = [
            "Понедельник", "Вторник", "Среда", 
            "Четверг", "Пятница", "Суббота", "Воскресенье"
        ]
        weekday = weekday_names[date.weekday()]
        
        # Если сегодня, добавляем пометку
        if i == 0:
            button_text = f"Сегодня, {date_str} ({weekday})"
        elif i == 1:
            button_text = f"Завтра, {date_str} ({weekday})"
        else:
            button_text = f"{date_str} ({weekday})"
        
        keyboard.append([
            InlineKeyboardButton(
                button_text, 
                callback_data=f"{CALLBACK_DATE_PREFIX}{date.isoformat()}"
            )
        ])
    
    # Добавляем кнопку "Отмена"
    keyboard.append([
        InlineKeyboardButton("Отмена", callback_data="cancel")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_time_keyboard(
    date: datetime.date, 
    duration_minutes: int
) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для выбора времени.
    
    Args:
        date (datetime.date): Выбранная дата
        duration_minutes (int): Длительность услуг в минутах
        
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с доступными временными слотами
    """
    # Получаем доступные слоты
    available_slots = get_available_slots(date, duration_minutes)
    
    keyboard = []
    
    # Если нет доступных слотов
    if not available_slots:
        keyboard.append([
            InlineKeyboardButton(
                "Нет доступных слотов на эту дату", 
                callback_data="no_slots"
            )
        ])
    else:
        # Группируем по 3 слота в ряду
        for i in range(0, len(available_slots), 3):
            row = []
            for slot in available_slots[i:i+3]:
                time_str = format_time_slot(slot)
                row.append(InlineKeyboardButton(
                    time_str,
                    callback_data=f"{CALLBACK_TIME_PREFIX}{slot.isoformat()}"
                ))
            keyboard.append(row)
    
    # Добавляем кнопку "Назад"
    keyboard.append([
        InlineKeyboardButton("Назад к выбору даты", callback_data="back_to_date")
    ])
    
    # Добавляем кнопку "Отмена"
    keyboard.append([
        InlineKeyboardButton("Отмена", callback_data="cancel")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для подтверждения записи.
    
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с кнопками подтверждения и отмены
    """
    keyboard = [
        [
            InlineKeyboardButton("Подтвердить запись", callback_data="confirm_appointment")
        ],
        [
            InlineKeyboardButton("Назад к выбору времени", callback_data="back_to_time")
        ],
        [
            InlineKeyboardButton("Отмена", callback_data="cancel")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_appointments_keyboard(appointments: List[Any]) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для просмотра записей.
    
    Args:
        appointments (List): Список записей пользователя
        
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с записями и кнопками действий
    """
    keyboard = []
    
    if not appointments:
        keyboard.append([
            InlineKeyboardButton("У вас нет активных записей", callback_data="no_appointments")
        ])
    else:
        for appointment in appointments:
            # Форматируем информацию о записи для кнопки
            start_time = appointment.start_time
            date_str = start_time.strftime("%d.%m.%Y")
            time_str = start_time.strftime("%H:%M")
            
            # Формируем текст кнопки
            if appointment.status == "PENDING":
                status_emoji = "⏳"
            elif appointment.status == "CONFIRMED":
                status_emoji = "✅"
            else:
                status_emoji = "❌"
                
            button_text = f"{status_emoji} {date_str} {time_str} ({appointment.status_text})"
            
            # Добавляем кнопку записи
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"{CALLBACK_APPOINTMENT_PREFIX}{appointment.id}"
                )
            ])
    
    # Добавляем кнопку "Назад в главное меню"
    keyboard.append([
        InlineKeyboardButton("Назад в главное меню", callback_data="back_to_main")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_appointment_actions_keyboard(appointment_id: int, status: str) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для действий с конкретной записью.
    
    Args:
        appointment_id (int): ID записи
        status (str): Статус записи
        
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с доступными действиями
    """
    keyboard = []
    
    # Кнопка отмены доступна только для неотмененных записей
    if status != "CANCELLED":
        keyboard.append([
            InlineKeyboardButton(
                "Отменить запись",
                callback_data=f"{CALLBACK_CANCEL_PREFIX}{appointment_id}"
            )
        ])
    
    # Добавляем кнопку "Назад к списку записей"
    keyboard.append([
        InlineKeyboardButton(
            "Назад к списку записей",
            callback_data="back_to_appointments"
        )
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Создает клавиатуру административного меню для мастера.
    
    Returns:
        ReplyKeyboardMarkup: Клавиатура с административными функциями
    """
    keyboard = [
        ["👥 Все записи", "📅 Записи на сегодня"],
        ["⏩ Записи на завтра"],
        ["🔄 Обновить", "🏠 Главное меню"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_admin_list_keyboard(appointments: List[Any]) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру со списком записей для администратора.
    
    Args:
        appointments (List): Список записей
        
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с записями
    """
    keyboard = []
    
    if not appointments:
        keyboard.append([
            InlineKeyboardButton("❌ Нет активных записей", callback_data="no_admin_appointments")
        ])
    else:
        # Сортируем записи по времени (сначала ближайшие)
        appointments = sorted(appointments, key=lambda x: x.start_time)
        
        for appointment in appointments:
            # Форматируем информацию о записи для кнопки
            start_time = appointment.start_time
            date_str = start_time.strftime("%d.%m.%Y")
            time_str = start_time.strftime("%H:%M")
            client_name = appointment.user.name if appointment.user else "Неизвестно"
            
            # Формируем текст кнопки с эмодзи статуса
            if appointment.status == "PENDING":
                status_emoji = "⏳"
            elif appointment.status == "CONFIRMED":
                status_emoji = "✅"
            else:
                status_emoji = "❌"
            
            # Добавляем информацию об услугах
            services_count = len(appointment.services_list)
            duration = appointment.duration_minutes
            
            button_text = f"{status_emoji} {date_str} {time_str} - {client_name} ({services_count} усл., {duration} мин)"
            
            # Добавляем кнопку записи
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"{CALLBACK_ADMIN_LIST}{appointment.id}"
                )
            ])
    
    # Добавляем кнопки управления
    keyboard.append([
        InlineKeyboardButton("🔍 Обновить список", callback_data="admin_refresh_list")
    ])
    
    # Добавляем кнопку возврата
    keyboard.append([
        InlineKeyboardButton("🔙 Назад в меню администратора", callback_data="back_to_admin_menu")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_admin_appointment_actions_keyboard(appointment_id: int, status: str) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для управления записью администратором.
    
    Args:
        appointment_id (int): ID записи
        status (str): Текущий статус записи
        
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с действиями
    """
    keyboard = []
    
    # Кнопки изменения статуса в зависимости от текущего статуса
    if status == "PENDING":
        keyboard.append([
            InlineKeyboardButton(
                "✅ Подтвердить запись", 
                callback_data=f"{CALLBACK_ADMIN_CONFIRM}{appointment_id}"
            )
        ])
        keyboard.append([
            InlineKeyboardButton(
                "❌ Отменить запись", 
                callback_data=f"{CALLBACK_ADMIN_CANCEL}{appointment_id}"
            )
        ])
    elif status == "CONFIRMED":
        keyboard.append([
            InlineKeyboardButton(
                "⏳ Изменить на 'Ожидает'", 
                callback_data=f"{CALLBACK_ADMIN_STATUS}PENDING:{appointment_id}"
            )
        ])
        keyboard.append([
            InlineKeyboardButton(
                "❌ Отменить запись", 
                callback_data=f"{CALLBACK_ADMIN_CANCEL}{appointment_id}"
            )
        ])
    elif status == "CANCELLED":
        keyboard.append([
            InlineKeyboardButton(
                "✅ Восстановить и подтвердить", 
                callback_data=f"{CALLBACK_ADMIN_CONFIRM}{appointment_id}"
            )
        ])
        keyboard.append([
            InlineKeyboardButton(
                "⏳ Восстановить как 'Ожидает'", 
                callback_data=f"{CALLBACK_ADMIN_STATUS}PENDING:{appointment_id}"
            )
        ])
    
    # Добавляем кнопку связи с клиентом
    keyboard.append([
        InlineKeyboardButton(
            "📱 Написать клиенту", 
            callback_data=f"admin_message_client:{appointment_id}"
        )
    ])
    
    # Добавляем кнопку возврата
    keyboard.append([
        InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_admin_list")
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_admin_confirmation_keyboard(appointment_id: int) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для подтверждения/отмены записи администратором.
    
    Args:
        appointment_id (int): ID записи
        
    Returns:
        InlineKeyboardMarkup: Инлайн-клавиатура с кнопками подтверждения и отмены
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "Подтвердить", 
                callback_data=f"{CALLBACK_ADMIN_CONFIRM}{appointment_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "Отменить", 
                callback_data=f"{CALLBACK_ADMIN_CANCEL}{appointment_id}"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# Обработчики команд и сообщений
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик команды /start.
    Приветствует пользователя и показывает главное меню.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    user = update.effective_user
    user_id = user.id
    is_admin = str(user_id) == MASTER_TELEGRAM_ID
    
    # Сохраняем пользователя в базу
    add_user(str(user_id), user.full_name)
    
    # Очищаем данные пользовательской сессии
    clear_user_data(user_id)
    
    # Отправляем приветственное сообщение с соответствующей клавиатурой
    await update.message.reply_text(
        f"Здравствуйте, {user.first_name}!\n\n"
        "Это бот для записи к парикмахеру.\n"
        f"Наш адрес: {BARBERSHOP_ADDRESS}\n\n"
        "Вы можете выбрать услуги и удобное время для записи.",
        reply_markup=get_main_menu_keyboard(is_admin)
    )
    
    return MAIN_MENU


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик главного меню.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    user_id = update.effective_user.id
    message_text = update.message.text
    is_admin = str(user_id) == MASTER_TELEGRAM_ID
    
    if message_text == "👨‍💼 Админ-панель" and is_admin:
        await update.message.reply_text(
            "Вы вошли в панель администратора.",
            reply_markup=get_admin_menu_keyboard()
        )
        return ADMIN_MENU
    
    elif message_text == "✅ Старт":
        # Отправляем приветственное сообщение и показываем главное меню
        await update.message.reply_text(
            f"Здравствуйте, {update.effective_user.first_name}!\n\n"
            "Добро пожаловать в бот для записи к парикмахеру.\n"
            f"Наш адрес: {BARBERSHOP_ADDRESS}\n\n"
            "Вы можете выбрать услуги и удобное время для записи.",
            reply_markup=get_main_menu_keyboard(is_admin)
        )
        return MAIN_MENU
    
    elif message_text == "Выбрать услугу":
        # Очищаем выбранные услуги
        user_data = get_user_data(user_id)
        user_data["selected_services"] = []
        
        # Показываем меню выбора услуг
        await update.message.reply_text(
            "Выберите услуги:",
            reply_markup=get_services_keyboard([])
        )
        return SELECTING_SERVICES
    
    elif message_text == "Мои записи":
        # Получаем записи пользователя
        appointments = get_user_appointments(str(user_id))
        
        if not appointments:
            await update.message.reply_text(
                "У вас нет активных записей.",
                reply_markup=get_main_menu_keyboard(is_admin)
            )
            return MAIN_MENU
        
        # Показываем список записей
        await update.message.reply_text(
            "Ваши записи:",
            reply_markup=get_appointments_keyboard(appointments)
        )
        return VIEWING_APPOINTMENTS
    
    else:
        # Неизвестная команда, показываем главное меню
        await update.message.reply_text(
            "Пожалуйста, выберите действие:",
            reply_markup=get_main_menu_keyboard(is_admin)
        )
        return MAIN_MENU


async def select_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик выбора услуг.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Обработка выбора услуги
    if query.data.startswith(CALLBACK_SERVICES_PREFIX):
        service_name = query.data[len(CALLBACK_SERVICES_PREFIX):]
        
        # Добавляем или удаляем услугу из выбранных
        if service_name in user_data["selected_services"]:
            user_data["selected_services"].remove(service_name)
        else:
            user_data["selected_services"].append(service_name)
        
        # Обновляем клавиатуру с выбранными услугами
        await query.edit_message_reply_markup(
            reply_markup=get_services_keyboard(user_data["selected_services"])
        )
        return SELECTING_SERVICES
    
    # Обработка нажатия кнопки "Готово"
    elif query.data == "services_done":
        selected_services = user_data["selected_services"]
        
        # Проверяем, что выбрана хотя бы одна услуга
        if not selected_services:
            await query.answer("Выберите хотя бы одну услугу!")
            return SELECTING_SERVICES
        
        # Переходим к выбору даты
        await query.edit_message_text(
            f"Выбрано услуг: {len(selected_services)}\n"
            f"Общая длительность: {calculate_total_duration(selected_services)} минут\n\n"
            "Выберите дату:",
            reply_markup=get_date_keyboard()
        )
        return SELECTING_DATE
    
    # Обработка отмены
    elif query.data == "cancel":
        await query.edit_message_text(
            "Запись отменена.",
            reply_markup=None
        )
        return MAIN_MENU
    
    return SELECTING_SERVICES


async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик выбора даты.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Обработка выбора даты
    if query.data.startswith(CALLBACK_DATE_PREFIX):
        date_str = query.data[len(CALLBACK_DATE_PREFIX):]
        selected_date = datetime.date.fromisoformat(date_str)
        
        # Проверяем валидность даты
        if not is_valid_date(selected_date):
            await query.answer("Выбрана невалидная дата!")
            return SELECTING_DATE
        
        # Сохраняем выбранную дату
        user_data["selected_date"] = selected_date
        
        # Получаем длительность выбранных услуг
        duration = calculate_total_duration(user_data["selected_services"])
        
        # Переходим к выбору времени
        await query.edit_message_text(
            f"Выбрана дата: {selected_date.strftime('%d.%m.%Y')}\n"
            f"Длительность услуг: {duration} минут\n\n"
            "Выберите время:",
            reply_markup=get_time_keyboard(selected_date, duration)
        )
        return SELECTING_TIME
    
    # Обработка отмены
    elif query.data == "cancel":
        await query.edit_message_text(
            "Запись отменена.",
            reply_markup=None
        )
        return MAIN_MENU
    
    return SELECTING_DATE


async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик выбора времени.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Обработка выбора времени
    if query.data.startswith(CALLBACK_TIME_PREFIX):
        time_str = query.data[len(CALLBACK_TIME_PREFIX):]
        selected_time = datetime.datetime.fromisoformat(time_str)
        
        # Сохраняем выбранное время
        user_data["selected_time"] = selected_time
        
        # Рассчитываем время окончания
        duration = calculate_total_duration(user_data["selected_services"])
        end_time = selected_time + datetime.timedelta(minutes=duration)
        
        # Формируем информацию о записи
        appointment_info = format_appointment_info(
            user_data["selected_services"],
            selected_time,
            end_time
        )
        
        # Переходим к подтверждению записи
        await query.edit_message_text(
            f"Подтвердите запись:\n\n{appointment_info}",
            reply_markup=get_confirm_keyboard()
        )
        return CONFIRMING_APPOINTMENT
    
    # Обработка кнопки "Назад к выбору даты"
    elif query.data == "back_to_date":
        await query.edit_message_text(
            "Выберите дату:",
            reply_markup=get_date_keyboard()
        )
        return SELECTING_DATE
    
    # Обработка случая, когда нет доступных слотов
    elif query.data == "no_slots":
        await query.answer("На эту дату нет доступных слотов. Выберите другую дату.")
        return SELECTING_TIME
    
    # Обработка отмены
    elif query.data == "cancel":
        await query.edit_message_text(
            "Запись отменена.",
            reply_markup=None
        )
        return MAIN_MENU
    
    return SELECTING_TIME


async def confirm_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик подтверждения записи.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    # Обработка подтверждения записи
    if query.data == "confirm_appointment":
        # Получаем данные для создания записи
        selected_services = user_data["selected_services"]
        selected_time = user_data["selected_time"]
        
        # Рассчитываем время окончания
        duration = calculate_total_duration(selected_services)
        end_time = selected_time + datetime.timedelta(minutes=duration)
        
        # Создаем запись в базе данных
        appointment_id = create_appointment(
            str(user_id),
            selected_services,
            selected_time,
            end_time
        )
        
        if appointment_id:
            # Отправляем уведомление пользователю
            await query.edit_message_text(
                "Ваша запись создана и ожидает подтверждения мастера.\n"
                "Вы получите уведомление, когда мастер подтвердит или отменит запись.",
                reply_markup=None
            )
            
            # Получаем информацию о записи вместе с данными пользователя для отправки мастеру
            appointment_data = get_appointment_with_user(appointment_id)
            
            if appointment_data:
                # Отправляем уведомление мастеру
                try:
                    # Формируем информацию о записи
                    appointment_info = format_appointment_info(
                        appointment_data['services_list'],
                        appointment_data['start_time'],
                        appointment_data['end_time']
                    )
                    
                    # Получаем данные о клиенте
                    client_name = appointment_data['user']['name']
                    
                    # Отправляем сообщение мастеру
                    await context.bot.send_message(
                        chat_id=MASTER_TELEGRAM_ID,
                        text=(
                            f"Новая заявка на запись!\n\n"
                            f"Клиент: {client_name}\n\n"
                            f"{appointment_info}"
                        ),
                        reply_markup=get_admin_confirmation_keyboard(appointment_id)
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления мастеру: {e}")
        else:
            # В случае ошибки при создании записи
            await query.edit_message_text(
                "Произошла ошибка при создании записи. Пожалуйста, попробуйте еще раз.",
                reply_markup=None
            )
        
        # Очищаем данные пользовательской сессии
        clear_user_data(user_id)
        
        return MAIN_MENU
    
    # Обработка кнопки "Назад к выбору времени"
    elif query.data == "back_to_time":
        selected_date = user_data["selected_date"]
        duration = calculate_total_duration(user_data["selected_services"])
        
        await query.edit_message_text(
            f"Выбрана дата: {selected_date.strftime('%d.%m.%Y')}\n"
            f"Длительность услуг: {duration} минут\n\n"
            "Выберите время:",
            reply_markup=get_time_keyboard(selected_date, duration)
        )
        return SELECTING_TIME
    
    # Обработка отмены
    elif query.data == "cancel":
        await query.edit_message_text(
            "Запись отменена.",
            reply_markup=None
        )
        return MAIN_MENU
    
    return CONFIRMING_APPOINTMENT


async def view_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик просмотра записей.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Обработка выбора конкретной записи
    if query.data.startswith(CALLBACK_APPOINTMENT_PREFIX):
        appointment_id = int(query.data[len(CALLBACK_APPOINTMENT_PREFIX):])
        
        # Получаем информацию о записи
        appointment = get_appointment_by_id(appointment_id)
        
        if appointment:
            # Формируем информацию о записи
            appointment_info = format_appointment_info(
                appointment.services_list,
                appointment.start_time,
                appointment.end_time
            )
            
            # Добавляем статус
            status_text = appointment.status_text
            
            await query.edit_message_text(
                f"Информация о записи:\n\n{appointment_info}\n\n"
                f"Статус: {status_text}",
                reply_markup=get_appointment_actions_keyboard(appointment_id, appointment.status)
            )
        else:
            await query.edit_message_text(
                "Запись не найдена или была удалена.",
                reply_markup=None
            )
        
        return VIEWING_APPOINTMENTS
    
    # Обработка отмены записи
    elif query.data.startswith(CALLBACK_CANCEL_PREFIX):
        appointment_id = int(query.data[len(CALLBACK_CANCEL_PREFIX):])
        
        # Отменяем запись
        if cancel_appointment(appointment_id):
            await query.edit_message_text(
                "Запись успешно отменена.",
                reply_markup=None
            )
            
            # Получаем информацию о записи вместе с данными пользователя для отправки мастеру
            appointment_data = get_appointment_with_user(appointment_id)
            
            if appointment_data:
                # Отправляем уведомление мастеру об отмене
                try:
                    # Формируем информацию о записи
                    appointment_info = format_appointment_info(
                        appointment_data['services_list'],
                        appointment_data['start_time'],
                        appointment_data['end_time']
                    )
                    
                    # Получаем данные о клиенте
                    client_name = appointment_data['user']['name']
                    
                    # Отправляем сообщение мастеру
                    await context.bot.send_message(
                        chat_id=MASTER_TELEGRAM_ID,
                        text=(
                            f"Клиент отменил запись!\n\n"
                            f"Клиент: {client_name}\n\n"
                            f"{appointment_info}"
                        )
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления мастеру: {e}")
        else:
            await query.edit_message_text(
                "Произошла ошибка при отмене записи. Пожалуйста, попробуйте еще раз.",
                reply_markup=None
            )
        
        return MAIN_MENU
    
    # Обработка кнопки "Назад к списку записей"
    elif query.data == "back_to_appointments":
        # Получаем записи пользователя
        appointments = get_user_appointments(str(user_id))
        
        await query.edit_message_text(
            "Ваши записи:",
            reply_markup=get_appointments_keyboard(appointments)
        )
        return VIEWING_APPOINTMENTS
    
    # Обработка кнопки "Назад в главное меню"
    elif query.data == "back_to_main":
        await query.edit_message_text(
            "Вы вернулись в главное меню.",
            reply_markup=None
        )
        return MAIN_MENU
    
    # Обработка случая, когда нет записей
    elif query.data == "no_appointments":
        await query.edit_message_text(
            "У вас нет активных записей.",
            reply_markup=None
        )
        return MAIN_MENU
    
    return VIEWING_APPOINTMENTS


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик административного меню.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    user_id = update.effective_user.id
    
    # Проверяем, что запрос от администратора
    if str(user_id) != MASTER_TELEGRAM_ID:
        await update.message.reply_text(
            "У вас нет прав на выполнение этого действия!",
            reply_markup=get_main_menu_keyboard(False)
        )
        return MAIN_MENU
    
    # Получаем текст сообщения
    message_text = update.message.text
    
    # Обработка команды возврата в главное меню клиента
    if message_text == "🏠 Главное меню":
        await update.message.reply_text(
            "Вы вернулись в главное меню клиента.",
            reply_markup=get_main_menu_keyboard(True)
        )
        return MAIN_MENU
    
    # Обработка команды обновления
    elif message_text == "🔄 Обновить":
        await update.message.reply_text(
            "Панель администратора обновлена.",
            reply_markup=get_admin_menu_keyboard()
        )
        return ADMIN_MENU
    
    # Определяем дату для фильтрации
    elif message_text == "📅 Записи на сегодня":
        date = datetime.date.today()
        title = "📅 Записи на сегодня"
    elif message_text == "⏩ Записи на завтра":
        date = datetime.date.today() + datetime.timedelta(days=1)
        title = "⏩ Записи на завтра"
    elif message_text == "👥 Все записи":
        date = None
        title = "👥 Все активные записи"
    else:
        # Неизвестная команда
        await update.message.reply_text(
            "Выберите действие из меню:",
            reply_markup=get_admin_menu_keyboard()
        )
        return ADMIN_MENU
    
    # Получаем записи
    from database import get_all_appointments, get_appointments_for_date
    
    if date:
        appointments = get_appointments_for_date(date)
    else:
        appointments = get_all_appointments()
    
    if not appointments:
        await update.message.reply_text(
            f"{title}:\n\nНет активных записей на указанный период.",
            reply_markup=get_admin_menu_keyboard()
        )
    else:
        # Отправляем список записей
        await update.message.reply_text(
            f"{title} ({len(appointments)}):",
            reply_markup=get_admin_list_keyboard(appointments)
        )
    
    return ADMIN_MENU


async def admin_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик изменения статуса записи администратором.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Проверяем, что запрос от администратора
    if str(user_id) != MASTER_TELEGRAM_ID:
        await query.answer("У вас нет прав на выполнение этого действия!")
        return MAIN_MENU
    
    # Получаем данные из callback_data
    # Формат: "admin_status:НОВЫЙ_СТАТУС:ID_ЗАПИСИ"
    if query.data.startswith(CALLBACK_ADMIN_STATUS):
        data_parts = query.data[len(CALLBACK_ADMIN_STATUS):].split(":")
        if len(data_parts) == 2:
            new_status, appointment_id = data_parts
            appointment_id = int(appointment_id)
            
            # Обновляем статус записи
            if update_appointment_status(appointment_id, new_status):
                status_text = APPOINTMENT_STATUSES.get(new_status, "Неизвестный статус")
                
                # Уведомляем об успешном изменении
                await query.answer(f"Статус изменен на: {status_text}")
                
                # Получаем обновленную информацию о записи
                appointment_data = get_appointment_with_user(appointment_id)
                
                if appointment_data:
                    # Формируем информацию о записи
                    appointment_info = format_appointment_info(
                        appointment_data['services_list'],
                        appointment_data['start_time'],
                        appointment_data['end_time']
                    )
                    
                    # Получаем данные о клиенте
                    client_name = appointment_data['user']['name']
                    client_telegram_id = appointment_data['user']['telegram_id']
                    
                    # Формируем статус с эмодзи
                    status = appointment_data['status']
                    if status == "PENDING":
                        status_emoji = "⏳"
                    elif status == "CONFIRMED":
                        status_emoji = "✅"
                    else:
                        status_emoji = "❌"
                    
                    # Обновляем сообщение с информацией о записи
                    await query.edit_message_text(
                        f"📋 Информация о записи #{appointment_data['id']}:\n\n"
                        f"👤 Клиент: {client_name}\n"
                        f"🆔 Telegram ID: {client_telegram_id}\n\n"
                        f"{appointment_info}\n\n"
                        f"🔄 Статус: {status_emoji} {appointment_data['status_text']}",
                        reply_markup=get_admin_appointment_actions_keyboard(
                            appointment_id, 
                            status
                        )
                    )
                    
                    # Отправляем уведомление клиенту об изменении статуса
                    try:
                        if new_status == "PENDING":
                            message_text = (
                                f"Статус вашей записи изменен на: ⏳ {status_text}\n\n"
                                f"{appointment_info}"
                            )
                        else:
                            message_text = (
                                f"Статус вашей записи изменен на: {status_emoji} {status_text}\n\n"
                                f"{appointment_info}"
                            )
                        
                        await context.bot.send_message(
                            chat_id=client_telegram_id,
                            text=message_text
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке уведомления клиенту: {e}")
                
                return ADMIN_MENU
            else:
                await query.answer("Ошибка при изменении статуса записи!")
                return ADMIN_MENU
    
    await query.answer("Неверный формат данных")
    return ADMIN_MENU


async def admin_view_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик для просмотра конкретной записи администратором.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Проверяем, что запрос от администратора
    if str(user_id) != MASTER_TELEGRAM_ID:
        await query.answer("У вас нет прав на выполнение этого действия!")
        return MAIN_MENU
    
    # Обработка просмотра конкретной записи
    if query.data.startswith(CALLBACK_ADMIN_LIST):
        appointment_id = int(query.data[len(CALLBACK_ADMIN_LIST):])
        
        # Получаем информацию о записи
        appointment_data = get_appointment_with_user(appointment_id)
        
        if appointment_data:
            # Формируем информацию о записи
            appointment_info = format_appointment_info(
                appointment_data['services_list'],
                appointment_data['start_time'],
                appointment_data['end_time']
            )
            
            # Получаем данные о клиенте
            client_name = appointment_data['user']['name']
            client_telegram_id = appointment_data['user']['telegram_id']
            
            # Формируем статус с эмодзи
            status = appointment_data['status']
            if status == "PENDING":
                status_emoji = "⏳"
            elif status == "CONFIRMED":
                status_emoji = "✅"
            else:
                status_emoji = "❌"
            
            # Отправляем информацию о записи
            await query.edit_message_text(
                f"📋 Информация о записи #{appointment_data['id']}:\n\n"
                f"👤 Клиент: {client_name}\n"
                f"🆔 Telegram ID: {client_telegram_id}\n\n"
                f"{appointment_info}\n\n"
                f"🔄 Статус: {status_emoji} {appointment_data['status_text']}",
                reply_markup=get_admin_appointment_actions_keyboard(
                    appointment_id, 
                    status
                )
            )
        else:
            await query.edit_message_text(
                "❌ Запись не найдена или была удалена.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_admin_list")
                ]])
            )
    
    # Обработка обновления списка записей
    elif query.data == "admin_refresh_list":
        # Получаем все записи
        from database import get_all_appointments
        appointments = get_all_appointments()
        
        # Отправляем обновленный список записей
        await query.edit_message_text(
            f"👥 Все активные записи ({len(appointments)}):",
            reply_markup=get_admin_list_keyboard(appointments)
        )
    
    # Обработка возврата к списку записей
    elif query.data == "back_to_admin_list":
        # Получаем все записи
        from database import get_all_appointments
        appointments = get_all_appointments()
        
        # Отправляем список записей
        await query.edit_message_text(
            f"👥 Все активные записи ({len(appointments)}):",
            reply_markup=get_admin_list_keyboard(appointments)
        )
    
    # Обработка возврата в админ-меню
    elif query.data == "back_to_admin_menu":
        await query.edit_message_text(
            "🔙 Вы вернулись в административное меню.",
            reply_markup=None
        )
    
    # Обработка случая с отсутствием записей
    elif query.data == "no_admin_appointments":
        await query.answer("В данный момент нет активных записей")
    
    return ADMIN_MENU


async def admin_confirm_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик подтверждения/отмены записи администратором.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: Следующее состояние диалога
    """
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Проверяем, что запрос от администратора
    if str(user_id) != MASTER_TELEGRAM_ID:
        await query.answer("У вас нет прав на выполнение этого действия!")
        return MAIN_MENU
    
    # Обработка подтверждения записи
    if query.data.startswith(CALLBACK_ADMIN_CONFIRM):
        appointment_id = int(query.data[len(CALLBACK_ADMIN_CONFIRM):])
        
        # Обновляем статус записи
        if update_appointment_status(appointment_id, "CONFIRMED"):
            await query.edit_message_text(
                "Запись подтверждена.",
                reply_markup=None
            )
            
            # Получаем информацию о записи для отправки клиенту
            appointment_data = get_appointment_with_user(appointment_id)
            
            if appointment_data:
                # Отправляем уведомление клиенту
                try:
                    # Формируем информацию о записи
                    appointment_info = format_appointment_info(
                        appointment_data['services_list'],
                        appointment_data['start_time'],
                        appointment_data['end_time']
                    )
                    
                    # Получаем данные о клиенте
                    client_telegram_id = appointment_data['user']['telegram_id']
                    
                    # Отправляем сообщение клиенту
                    await context.bot.send_message(
                        chat_id=client_telegram_id,
                        text=(
                            f"Ваша запись подтверждена мастером!\n\n"
                            f"{appointment_info}\n\n"
                            f"Ждем вас по адресу: {BARBERSHOP_ADDRESS}"
                        )
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления клиенту: {e}")
        else:
            await query.answer("Произошла ошибка при подтверждении записи!")
    
    # Обработка отмены записи администратором
    elif query.data.startswith(CALLBACK_ADMIN_CANCEL):
        appointment_id = int(query.data[len(CALLBACK_ADMIN_CANCEL):])
        
        # Отменяем запись
        if cancel_appointment(appointment_id):
            await query.edit_message_text(
                "❌ Запись отменена успешно!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад к списку записей", callback_data="back_to_admin_list")
                ]])
            )
            
            # Получаем информацию о записи для отправки клиенту
            appointment_data = get_appointment_with_user(appointment_id)
            
            if appointment_data:
                # Отправляем уведомление клиенту
                try:
                    # Формируем информацию о записи
                    appointment_info = format_appointment_info(
                        appointment_data['services_list'],
                        appointment_data['start_time'],
                        appointment_data['end_time']
                    )
                    
                    # Получаем данные о клиенте
                    client_telegram_id = appointment_data['user']['telegram_id']
                    
                    # Отправляем сообщение клиенту
                    await context.bot.send_message(
                        chat_id=client_telegram_id,
                        text=(
                            f"К сожалению, ваша запись была отменена мастером.\n\n"
                            f"{appointment_info}\n\n"
                            f"Пожалуйста, выберите другое время или свяжитесь с мастером."
                        )
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления клиенту: {e}")
        else:
            await query.answer("Произошла ошибка при отмене записи!")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик отмены текущего диалога.
    
    Args:
        update (Update): Объект обновления Telegram
        context (ContextTypes.DEFAULT_TYPE): Контекст
        
    Returns:
        int: MAIN_MENU - возврат в главное меню
    """
    user_id = update.effective_user.id
    
    # Очищаем данные пользовательской сессии
    clear_user_data(user_id)
    
    # Отправляем сообщение о возврате в главное меню
    if update.message:
        # Проверяем, является ли пользователь администратором
        if str(user_id) == MASTER_TELEGRAM_ID:
            await update.message.reply_text(
                "Операция отменена. Вы вернулись в меню администратора.",
                reply_markup=get_main_menu_keyboard(True)
            )
            return MAIN_MENU
        else:
            await update.message.reply_text(
                "Операция отменена. Вы вернулись в главное меню.",
                reply_markup=get_main_menu_keyboard(False)
            )
            return MAIN_MENU
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            "Операция отменена. Вы вернулись в главное меню.",
            reply_markup=None
        )
        
        # Проверяем, является ли пользователь администратором
        if str(user_id) == MASTER_TELEGRAM_ID:
            return ADMIN_MENU
        else:
            return MAIN_MENU


def main() -> None:
    """
    Основная функция для запуска бота.
    """
    # Создаем таблицы в базе данных
    create_tables()
    
    # Создаем экземпляр приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Создаем обработчик разговора
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)
            ],
            ADMIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_menu),
                CallbackQueryHandler(admin_view_appointment, pattern=f"^({CALLBACK_ADMIN_LIST}|back_to_admin_list|back_to_admin_menu|admin_refresh_list|no_admin_appointments).*$"),
                CallbackQueryHandler(admin_confirm_appointment, pattern=f"^({CALLBACK_ADMIN_CONFIRM}|{CALLBACK_ADMIN_CANCEL}).*$"),
                CallbackQueryHandler(admin_status_change, pattern=f"^{CALLBACK_ADMIN_STATUS}.*$"),
            ],
            SELECTING_SERVICES: [
                CallbackQueryHandler(select_services)
            ],
            SELECTING_DATE: [
                CallbackQueryHandler(select_date)
            ],
            SELECTING_TIME: [
                CallbackQueryHandler(select_time)
            ],
            CONFIRMING_APPOINTMENT: [
                CallbackQueryHandler(confirm_appointment)
            ],
            VIEWING_APPOINTMENTS: [
                CallbackQueryHandler(view_appointments)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Добавляем обработчики
    application.add_handler(conv_handler)
    
    # Эти обработчики уже включены в ConversationHandler в состоянии ADMIN_MENU
    
    # Запускаем бота
    application.run_polling()


if __name__ == "__main__":
    main()

