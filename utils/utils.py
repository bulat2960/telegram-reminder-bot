from datetime import datetime

months = {
    'Январь': 1,
    'Февраль': 2,
    'Март': 3,
    'Апрель': 4,
    'Май': 5,
    'Июнь': 6,
    'Июль': 7,
    'Август': 8,
    'Сентябрь': 9,
    'Октябрь': 10,
    'Ноябрь': 11, 
    'Декабрь': 12
}

genitive_months = {
    1: 'января',
    2: 'февраля',
    3: 'марта',
    4: 'апреля',
    5: 'мая',
    6: 'июня',
    7: 'июля',
    8: 'августа',
    9: 'cентября',
    10: 'октября',
    11: 'ноября',
    12: 'декабря'
}

# ------------------ UTILS ------------------ #

def is_leap(year):
    if year % 4 == 0 and year % 100 != 0 or year % 400 == 0:
        return True
    return False

def get_days_by_month_and_year(year, month):
    months_30_days = ['Апрель', 'Июнь', 'Сентябрь', 'Ноябрь']
    months_31_days = ['Январь', 'Март', 'Май', 'Июль', 'Август', 'Октябрь', 'Декабрь']
    days_in_february = 29 if is_leap(year) else 28

    if month in months_30_days:
        return 30
    elif month in months_31_days:
        return 31
    return days_in_february

def get_month_by_name(month):
    return months[month]

def get_month_in_genitive(month_number):
    return genitive_months[int(month_number)]

def get_months_list():
    return months.keys()

def get_years_list():
    return [datetime.now().year, datetime.now().year + 1]