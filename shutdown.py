import os
from datetime import timedelta

# 设置3小时的延迟
delay = timedelta(hours=5).seconds

# 创建一个关机命令
command = f"shutdown /s /t {delay}"

# 调用关机命令
os.system(command)

# 向用户提供反馈
print(f"关机已安排，系统将在{delay / 3600}小时后关闭。")
