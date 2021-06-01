import threading
import time
import schedule
from time import sleep

class ScheduleThread(threading.Thread):
    die = False
    def __init__(self):
        threading.Thread.__init__(self)

    def run(self):
        while not self.die:
            schedule.run_pending()
            sleep(1)

    def join(self):
        self.die = True
        super().join()