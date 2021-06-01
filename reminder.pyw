import telebot
from telebot import types
import schedule
from threading import Thread
from time import sleep
from datetime import date, datetime
import psycopg2
from functools import partial
import time
import uuid
import sys

from utils.utils import get_days_by_month_and_year, get_month_by_name, get_months_list, get_month_in_genitive, get_years_list

from schedule_thread import ScheduleThread
import settings

bot = telebot.TeleBot(settings.reminder_bot_token)

connection = psycopg2.connect("host={0} dbname={1} user={2} password={3}".format(
                               settings.db_host, 
                               settings.db_name,
                               settings.db_user,
                               settings.db_password))

cursor = connection.cursor()

TASKS = "tasks"
USERS = "users"
YES = "Да"
NO = "Нет"

yes_no_list = [YES, NO]
tasks_statuses = ["Выполнено", "В процессе"]
tasks_switches = ["Включить", "Выключить"]


# ------------------ DATABASE METHODS ------------------ #

def SELECT(fields):
    if isinstance(fields, list):
        fields = ", ".join(fields)
    return f"SELECT {fields}"

def FROM(table):
    return "FROM {}".format(table)

def WHERE(condition_list):
    return "WHERE " + " AND ".join(condition_list)

def WHERE_IN(search_key, in_list):
    return "WHERE {} IN ({})".format(search_key, ", ".join(map(str, in_list)))

def LIMIT(value):
    return f"LIMIT {value}"

def UPDATE(table, key, value):
    return f"UPDATE {table} SET {key} = {with_quotes(value)}"

def DELETE(table):
    return "DELETE FROM {}".format(table)

def INSERT(table, data):
    return "INSERT INTO {} VALUES (default, {})".format(table, ", ".join(str(x) for x in data))

def COUNT(fields):
    return "COUNT({})".format(", ".join(str(x) for x in fields))

def build_select_query(fields, table, condition_list=None, count=False, limit=None):
    if count == True:
        fields = COUNT(fields)

    if condition_list is not None:
        query = " ".join([SELECT(fields), FROM(table), WHERE(condition_list)])
    else:
        query = " ".join([SELECT(fields), FROM(table)])

    if limit is not None:
        query += ' ' + LIMIT(limit)

    return query

def build_update_query(table, key, value, condition_list):
    return " ".join([UPDATE(table, key, value), WHERE(condition_list)])

def build_update_in_query(table, key, value, search_key, in_list):
    return " ".join([UPDATE(table, key, value), WHERE_IN(search_key, in_list)])

def build_delete_query(table, condition_list=None):
    query = ""
    if condition_list is not None:
        query = " ".join([DELETE(table), WHERE(condition_list)])
    else:
        query = DELETE(table)
    return query

def build_delete_in_query(table, key, in_list):
   return " ".join([DELETE(table), WHERE_IN(key, in_list)])

def build_insert_query(table, data):
    return INSERT(table, data)

def process_query(query):
    cursor.execute(query)
    connection.commit()

    if query.split()[0] == "SELECT":
        data = cursor.fetchall()
        return data

def build_exists_query(table, key, value):
    return build_select_query(fields="*", table=table, condition_list=[f"{key} = {with_quotes(value)}"])

def task_exists(key):
    query = build_exists_query(table="tasks", key="key", value=key)
    data = process_query(query)

    if len(data) == 0:
        return False

    return True

def is_notifications_on(chat_id):
    query = build_select_query(fields="*", table=USERS, condition_list=["notifications_status = True", f"chat_id = {chat_id}"])
    data = process_query(query)

    if len(data) == 0:
        return False

    return True

def get_tasks(fields="*", condition_list=None, count=False, limit=None):
    query = build_select_query(fields=fields, table=TASKS, condition_list=condition_list, count=count, limit=limit)
    data = process_query(query)
    return data

def get_or_create_user_id(chat_id):
    query = build_select_query(fields="*", table=USERS, condition_list=[f"chat_id = {chat_id}"])
    data = process_query(query)

    if len(data) == 0:
        add_user_query = build_insert_query(USERS, [chat_id, True])
        data = process_query(add_user_query)

    for [id, user_chat_id, *other] in data:
        if user_chat_id == chat_id:
            return id


# ------------------ USEFUL METHODS ------------------ #

def with_quotes(value):
    return f"'{value}'"

def create_markup(data):
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)

    for elem in data:
        markup.row(str(elem))

    return markup

def generate_key():
    return uuid.uuid4().hex[0:7]

def input_is_command_like(text):
    return text[0] == '/'

def is_integer(n):
    try:
        int(n)
    except ValueError:
        return False
    return True

# ------------------ ADD TASK HANDLER ------------------ #

class TaskData:
    def __init__(self):
        self.key = None
        self.description = None
        self.day = None
        self.month = None
        self.year = None
        self.periodicity = None

    def clear(self):
        self.key = None
        self.description = None
        self.day = None
        self.month = None
        self.year = None
        self.periodicity = None

task_data = TaskData()

@bot.message_handler(commands=['add'])
def add_task_handler(message):
    task_data.clear()

    bot.send_message(chat_id=message.chat.id, text="Введите описание задачи (или 'exit' для отмены)")
    bot.register_next_step_handler(message, input_task_description)

def input_task_description(message):
    if input_is_command_like(message.text):
        bot.send_message(chat_id=message.chat.id, text="Необходимо ввести описание задачи, а не команду")
        bot.register_next_step_handler(message, input_task_description)
        return

    task_data.description = message.text

    if message.text.lower() == 'exit':
        bot.send_message(chat_id=message.chat.id, reply_markup=types.ReplyKeyboardRemove(), text="Операция добавления задачи прервана")
        return

    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(YES, NO)

    msg = bot.send_message(chat_id=message.chat.id, 
                           reply_markup=markup, 
                           text="Вы хотите добавить дедлайн для данной задачи?")

    bot.register_next_step_handler(msg, check_if_need_expiration_date_input)

def check_if_need_expiration_date_input(message):
    if message.text not in yes_no_list:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, check_if_need_expiration_date_input)
        return

    if message.text == YES:
        start_expiration_date_sequence(message)
    else:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add(YES, NO)

        msg = bot.send_message(chat_id=message.chat.id, 
                               reply_markup=markup, 
                               text="Вы хотите добавить частоту уведомлений для данной задачи?")

        bot.register_next_step_handler(msg, check_if_need_reminder_periodicity)                 

def check_if_need_reminder_periodicity(message):
    if message.text not in yes_no_list:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, check_if_need_reminder_periodicity)
        return

    if message.text == YES:
        input_task_reminder_periodicity(message)
    else:
        execute_add_task_query(message.chat.id)      

def start_expiration_date_sequence(message):
    [year, next_year] = get_years_list()

    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(str(year), str(next_year))

    msg = bot.send_message(chat_id=message.chat.id, reply_markup=markup, text="Выберите год")
    bot.register_next_step_handler(msg, input_task_expiration_year)

def input_task_expiration_year(message):
    if int(message.text) not in get_years_list() or not is_integer(int(message.text)):
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, input_task_expiration_year)
        return

    task_data.year = int(message.text)

    markup = create_markup(get_months_list())

    msg = bot.send_message(chat_id=message.chat.id, reply_markup=markup, text="Выберите месяц")
    bot.register_next_step_handler(msg, input_task_expiration_month)

def input_task_expiration_month(message):
    if message.text not in get_months_list():
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, input_task_expiration_month)
        return

    month = message.text
    days_number = get_days_by_month_and_year(task_data.year, month)
    task_data.month = get_month_by_name(month)

    markup = create_markup(list(range(1, days_number + 1)))

    msg = bot.send_message(chat_id=message.chat.id, reply_markup=markup, text="Выберите день")
    bot.register_next_step_handler(msg, input_task_expiration_day)

def input_task_expiration_day(message):
    days_in_current_month = get_days_by_month_and_year(task_data.year, task_data.month) + 1
    if not is_integer(message.text) or int(message.text) not in range(1, days_in_current_month):
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, input_task_expiration_day)
        return

    task_data.day = int(message.text)

    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(YES, NO)

    msg = bot.send_message(chat_id=message.chat.id, 
                           reply_markup=markup, 
                           text="Вы хотите добавить частоту уведомлений для данной задачи?")

    bot.register_next_step_handler(msg, check_if_need_reminder_periodicity)   


periodicity_dict = {"Каждый час": 1,
                    "Каждые 6 часов": 6,
                    "Каждые сутки": 24,
                    "Каждую неделю": 24 * 7,
                    "Каждый месяц": 24 * 7 * 30}


def input_task_reminder_periodicity(message):
    markup = create_markup(periodicity_dict.keys())

    msg = bot.send_message(chat_id=message.chat.id, reply_markup=markup, text="Выберите частоту уведомлений")
    bot.register_next_step_handler(msg, finish_sequence_and_execute_add_task)

def finish_sequence_and_execute_add_task(message):
    if message.text not in periodicity_dict.keys():
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, finish_sequence_and_execute_add_task)
        return

    periodicity = message.text
    task_data.periodicity = periodicity_dict[periodicity]

    execute_add_task_query(message.chat.id)

def execute_add_task_query(chat_id):
    today_day = date.today().day
    today_month = date.today().month
    today_year = date.today().year

    user_id = get_or_create_user_id(chat_id)

    task_data.key = generate_key()

    query = build_insert_query(TASKS, 
                [f"'{task_data.key}'",
                 f"'{task_data.description}'",
                 f"'{today_year}-{today_month}-{today_day}'",
                 f"'{task_data.year}-{task_data.month}-{task_data.day}'" if task_data.year is not None else 'NULL',
                 f"{task_data.periodicity}" if task_data.periodicity is not None else 'NULL',
                 "'В процессе'",
                 user_id])

    process_query(query)

    bot.send_message(chat_id=chat_id, 
                    reply_markup=types.ReplyKeyboardRemove(),
                    text="Задача '{}' {} и {} была успешно добавлена".format(
                    task_data.description,
                    'без даты дедлайна' if task_data.year is None 
                    else 'с датой дедлайна {} {} {}'.format(task_data.day, 
                                                            get_month_in_genitive(task_data.month), 
                                                            task_data.year),
                    'без уведомлений' if task_data.periodicity is None 
                    else 'с уведомлениями раз в {} часов'.format(task_data.periodicity)
    ))

    if (task_data.periodicity is not None):
        schedule.every(task_data.periodicity).hours.do(
            partial(send_task, chat_id, task_data.key)
        )

    schedule.every(30).minutes.do(
        partial(track_deadline, chat_id, task_data.key)
    )
        

# ------------------ DELETE TASK HANDLER ------------------ #

@bot.message_handler(commands=['delete'])
def delete_task_handler(message):
    user_id = get_or_create_user_id(message.chat.id)
    rows = get_tasks(fields=["key", "description", "status"], condition_list=[f"user_id = {user_id}"])
    
    keys = []
    text = ""
    for [key, name, status] in rows:
        keys.append(key)
        text += "{0}: {1} ({2})\n".format(key, name, status)

    if len(keys) == 0:
        bot.send_message(chat_id=message.chat.id, text="Нет активных задач")
        return

    markup = create_markup(keys)

    msg = bot.send_message(chat_id=message.chat.id, reply_markup=markup, text="Выберите ключ для удаления\n\n{}".format(text))
    bot.register_next_step_handler(msg, finish_sequence_and_execute_delete_task)

def finish_sequence_and_execute_delete_task(message):
    key = message.text
    delete_task(message.chat.id, key)
    bot.send_message(chat_id=message.chat.id, reply_markup=types.ReplyKeyboardRemove(), text=f"Задача '{key}' успешно удалена")

def delete_task(chat_id, key):
    user_id = get_or_create_user_id(chat_id)
    query = build_delete_query(table=TASKS, condition_list=[f"key = {with_quotes(key)}", f"user_id = {user_id}"])
    process_query(query)

# ------------------ MARK TASK HANDLER SECTION ------------------ #

class MarkData:
    def __init__(self):
        self.key = None
        self.status = None

    def clear(self):
        self.key = None
        self.status = None

mark_data = MarkData()

@bot.message_handler(commands=['mark'])
def mark_task_handler(message):
    user_id =  get_or_create_user_id(message.chat.id)
    rows = get_tasks(fields=["key", "description", "status"], condition_list=[f"user_id = {user_id}"])

    keys = []
    text = ""
    for [key, name, status] in rows:
        keys.append(key)
        text += "{0}: {1} ({2})\n".format(key, name, status)

    if len(keys) == 0:
        bot.send_message(chat_id=message.chat.id, text="Нет активных задач")
        return

    markup = create_markup(keys)

    msg = bot.send_message(chat_id=message.chat.id, 
                           reply_markup=markup, 
                           text="Выберите задачу для изменения статуса\n\n{}".format(text))
    bot.register_next_step_handler(msg, set_new_status)

def set_new_status(message):
    mark_data.key = message.text

    markup = create_markup(tasks_statuses)

    msg = bot.send_message(chat_id=message.chat.id, reply_markup=markup, text="Установите новый статус")
    bot.register_next_step_handler(msg, finish_sequence_and_execute_change_status)

def finish_sequence_and_execute_change_status(message):
    if message.text not in tasks_statuses:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, finish_sequence_and_execute_change_status)
        return
    
    mark_data.status = message.text

    change_task_status(message.chat.id)
    bot.send_message(chat_id=message.chat.id, reply_markup=types.ReplyKeyboardRemove(),
                     text=f"Статус задачи '{mark_data.key}' успешно изменен на '{message.text}'")

def change_task_status(chat_id):
    user_id = get_or_create_user_id(chat_id)

    query = build_update_query(TASKS, "status", mark_data.status, [f"key = {with_quotes(mark_data.key)}", f"user_id = {user_id}"])
    process_query(query)


# ------------------ HELPER FUNCTIONS SECTION ------------------ #

def schedule_checker():
    while True:
        schedule.run_pending()
        sleep(1)

def send_task(chat_id, key):
    if not is_notifications_on(chat_id):
        return schedule.CancelJob

    query = build_select_query(fields=["key", "description", "date_expired", "status"], table=TASKS, 
                               condition_list=[f"key = {with_quotes(key)}"])
    data = process_query(query)

    if len(data) == 0:
        return schedule.CancelJob

    row = data[0]

    [key, description, date_expired, status] = row

    if status == "Выполнено":
        return schedule.CancelJob
    
    bot.send_message(chat_id=chat_id,
                     text="Напоминание о задаче\nКлюч: {}\nЗадача: {}\nДедлайн: {}\nСтатус: {}".format(
                        key, 
                        description, 
                        date_expired if date_expired is not None else "Не назначено",
                        status))

def track_deadline(chat_id, key):
    if not is_notifications_on(chat_id):
        return schedule.CancelJob

    query = build_select_query(fields=["key", "description", "date_expired"], table=TASKS, 
                               condition_list=[f"key = {with_quotes(key)}"])
    data = process_query(query)

    if len(data) == 0:
        return schedule.CancelJob

    row = data[0]

    [key, description, date_expired] = row

    remaining_time = datetime(date_expired.year, date_expired.month, date_expired.day) - datetime.now()
    remaining_seconds = remaining_time.total_seconds()

    if 0 <= remaining_seconds <= 3600 * 3:
        bot.send_message(chat_id=chat_id, text="Близок дедлайн!\nКлюч: {}\nЗадача: {}\nДедлайн: {}".format(
            key, 
            description, 
            f"{date_expired.day} {get_month_in_genitive(int(date_expired.month))} {date_expired.year}"
        ))
        return schedule.CancelJob

def check_done_tasks():
    query = build_delete_query(table=TASKS, condition_list=[f"status = {with_quotes('Выполнено')}"])
    process_query(query)

def check_expired_tasks():
    current_date = date.today().strftime("%Y-%m-%d")

    query = build_update_query(TASKS, "status", "Просрочено", condition_list=[f"date_added > {with_quotes(current_date)}"])
    process_query(query)


# ------------------ COMMANDS SECTION ------------------ #

@bot.message_handler(commands=['show'])
def show_tasks_handler(message):
    data_list = message.text.split()

    text = ""

    if len(data_list) != 1:
        text = "Для этой команды не нужно предоставлять дополнительных параметров"
    else:
        user_id = get_or_create_user_id(message.chat.id)

        rows = get_tasks(fields=["key", "description", "date_added", "date_expired", "reminder_periodicity", "status"],
                         condition_list=[f"user_id = {user_id}"])

        for [key, description, date_added, date_expired, periodicity, status] in rows:
            year_added, month_added, day_added = str(date_added).split("-")
            year_expired, month_expired, day_expired = 0, 0, 0 

            if date_expired is not None:
                year_expired, month_expired, day_expired = str(date_expired).split("-")

            text += "Ключ: {0}\nЗадача: {1}\nДобавлено: {2}\nДедлайн: {3}\nУведомления: {4}\nСтатус: {5}".format(
                    key,
                    description,
                    "{} {} {}".format(day_added, get_month_in_genitive(month_added), year_added),
                    "{} {} {}".format(day_expired, get_month_in_genitive(month_expired), year_expired) 
                        if year_expired != 0 else "Не назначено",
                    "Каждые {} часов".format(periodicity) if periodicity is not None else "Не назначено",
                    status)
            text += "\n\n"
        
    if len(text) == 0:
        text = "Нет активных задач"

    bot.send_message(chat_id=message.chat.id, text=text)

@bot.message_handler(commands=['notifications'])
def notify_tasks_handler(message):
    data_list = message.text.split()

    if len(data_list) != 1:
        bot.send_message(chat_id=message.chat.id, text = "Для этой команды не нужно предоставлять дополнительных параметров")
        return 

    user_id = get_or_create_user_id(message.chat.id)

    markup = create_markup(tasks_switches)

    msg = bot.send_message(chat_id=message.chat.id, reply_markup=markup, text="Вы хотите включить или выключить уведомления?")
    bot.register_next_step_handler(msg, change_notifications_status)

def change_notifications_status(message):
    if message.text not in tasks_switches:
        bot.send_message(chat_id=message.chat.id, text="Пожалуйста, нажмите на нужный вариант или введите его вручную")
        bot.register_next_step_handler(message, change_notifications_status)
        return

    text = message.text

    query = build_select_query(fields=["id", "notifications_status"], table=USERS, 
                               condition_list=[f"chat_id = {message.chat.id}"])

    cursor.execute(query)
    connection.commit()

    row = cursor.fetchone()

    [id, notifications_status] = row

    new_notification_status_is_on = True if text == "Включить" else False

    query = build_update_query(USERS, "notifications_status", new_notification_status_is_on, [f"id = {id}"])
    process_query(query)

    if new_notification_status_is_on:
        user_id = get_or_create_user_id(message.chat.id)
        start_scheduled_tasks_tracking(user_id)
        start_deadline_tasks_tracking(user_id)

    status = "включены" if new_notification_status_is_on else "отключены"
    bot.send_message(chat_id=message.chat.id, reply_markup=types.ReplyKeyboardRemove(), text=f"Уведомления {status}")

@bot.message_handler(commands=['help', 'start'])
def help_handler(message):
    text = "/add Добавить задачу\n" \
           "/delete Удалить задачу\n" \
           "/show Показать список активных задач\n" \
           "/mark Обновить статус задачи\n" \
           "/help Показать справку\n" \
           "/notifications Включить/выключить уведомления"

    bot.send_message(chat_id=message.chat.id, text=text)

def start_scheduled_tasks_tracking(user_id=None):
    query = "SELECT key, description, date_added, date_expired, reminder_periodicity, status, chat_id, notifications_status \
             FROM tasks INNER JOIN users ON user_id = users.id"

    if user_id is not None:
        query += " WHERE user_id = {}".format(user_id)

    rows = process_query(query)

    for [key, description, date_added, date_expired, reminder_periodicity, status, chat_id, notifications_status] in rows:
        year, month, day = None, None, None
        if date_expired is not None:
            year, month, day = str(date_expired).split("-")
            month = get_month_in_genitive(month)

        if (reminder_periodicity is not None) and (notifications_status is True):
            schedule.every(reminder_periodicity).hours.do(
                partial(send_task, chat_id, key)
            )

def start_deadline_tasks_tracking(user_id=None):
    query = "SELECT key, description, date_added, date_expired, reminder_periodicity, status, chat_id, notifications_status \
             FROM tasks INNER JOIN users ON user_id = users.id"

    if user_id is not None:
        query += " WHERE user_id = {}".format(user_id)

    rows = process_query(query)

    for [key, description, date_added, date_expired, reminder_periodicity, status, chat_id, notifications_status] in rows:
        if date_expired is not None:
            year, month, day = str(date_expired).split("-")
            month = get_month_in_genitive(month)

            if (notifications_status is True):
                schedule.every(30).minutes.do(
                    partial(track_deadline, chat_id, key)
                )

# ------------------ PROGRAM START SECTION ------------------ #

if __name__ == "__main__":
    schedule.every().day.at("00:00").do(check_done_tasks)
    schedule.every(10).seconds.do(check_expired_tasks)

    start_scheduled_tasks_tracking()
    start_deadline_tasks_tracking()

    schedule_thread = ScheduleThread()
    schedule_thread.start()

    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            exception_type, exception_object, exception_traceback = sys.exc_info()
            filename = exception_traceback.tb_frame.f_code.co_filename
            line_number = exception_traceback.tb_lineno

            print("Exception type: ", exception_type)
            print("File name: ", filename)
            print("Line number: ", line_number)

            time.sleep(3)
    
    schedule_thread.join()