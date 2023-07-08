from pynput.keyboard import Key, Listener
import time

log = {}
results = []

def on_press(key):
    global log
    timestamp = time.time() * 1000  # 转换为毫秒
    # 如果键在字典中不存在，则创建一个新的键值对
    if key not in log:
        log[key] = [timestamp, 0]
    else:
        log[key][0] = timestamp

def on_release(key):
    global log, results
    timestamp = time.time() * 1000  # 转换为毫秒
    # 如果键在字典中存在，则记录释放时间，并计算持续时间
    if key in log and log[key][0] != 0:
        log[key][1] = timestamp
        duration = log[key][1] - log[key][0]
        results.append((str(key), 'press', round(duration, 2)))
        results.append((str(key), 'release', 0))
        log[key] = [0, 0]  # 重置时间以供下一次按键

    # 如果我们想在按 Esc 键时停止监听器
    if key == Key.esc:
        return False

# 监听按键
with Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()

# 打印日志
for record in results:
    print(record)
