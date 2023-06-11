"""The central program that ties all the modules together."""

import time
from easymaple.modules.bot import Bot
from easymaple.modules.capture import Capture
from easymaple.modules.notifier import Notifier
from easymaple.modules.listener import Listener
from easymaple.modules.gui import GUI


bot = Bot()
capture = Capture()
notifier = Notifier()
listener = Listener()

bot.start()
while not bot.ready:
    time.sleep(0.01)

capture.start()
while not capture.ready:
    time.sleep(0.01)

notifier.start()
while not notifier.ready:
    time.sleep(0.01)

listener.start()
while not listener.ready:
    time.sleep(0.01)

print('\n[~] Successfully initialized Auto Maple')

gui = GUI()
gui.start()
