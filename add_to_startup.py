import os


def add_to_startup(file_path=""):
    if file_path == "":
        file_path = os.path.dirname(os.path.realpath(__file__))
    bat_path = "C:\\Users\\buzom\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
    with open(bat_path + '\\' + "reminder_bot.bat", "w+") as bat_file:
        bat_file.write(f'start "" {file_path}')

if __name__ == "__main__":
    add_to_startup("D:\\Dev\\python\\telegram-bots\\reminder\\reminder.pyw")