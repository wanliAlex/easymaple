"""EasyMaple - An automated MapleStory bot with GUI, minimap tracking, and routine execution."""

__version__ = "0.1.0"

__all__ = [
    "Bot",
    "Capture",
    "Notifier",
    "Listener",
    "GUI",
    "Routine",
    "main",
]


def __getattr__(name):
    """Lazy imports so the package can be imported on non-Windows systems without crashing."""

    if name == "Bot":
        from easymaple.modules.bot import Bot
        return Bot
    if name == "Capture":
        from easymaple.modules.capture import Capture
        return Capture
    if name == "Notifier":
        from easymaple.modules.notifier import Notifier
        return Notifier
    if name == "Listener":
        from easymaple.modules.listener import Listener
        return Listener
    if name == "GUI":
        from easymaple.modules.gui import GUI
        return GUI
    if name == "Routine":
        from easymaple.routine.routine import Routine
        return Routine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main():
    """Entry point that initializes and starts all modules."""

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

    print('\n[~] Successfully initialized EasyMaple')

    gui = GUI()
    gui.start()
