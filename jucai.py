import time
from pynput.mouse import Button, Controller as MouseController, Listener as MouseListener
from pynput.keyboard import Controller as KeyboardController, Listener as KeyboardListener, Key, KeyCode

<<<<<<< HEAD
# Initialize mouse and keyboard controllers
mouse = MouseController()
keyboard = KeyboardController()

# Set a special hotkey to start or stop the program
start_stop_key = KeyCode(char='s')

# Flag to control if the program is running
running = False

# Behavior when a key is pressed
def on_press(key):
    global running
    if key == start_stop_key:
        running = not running  # Toggle running state

# Use a keyboard listener
listener = KeyboardListener(on_press=on_press)
listener.start()

# Behavior when the mouse is clicked
=======
# 初始化鼠标和键盘控制器
mouse = MouseController()
keyboard = KeyboardController()

# 设定一个特殊的热键来启动或停止程序
start_stop_key = KeyCode(char='s')

# 控制程序是否运行的标志
running = False

# 在键盘按下时的行为
def on_press(key):
    global running
    if key == start_stop_key:
        running = not running  # 切换运行状态

# 使用键盘监听器
listener = KeyboardListener(on_press=on_press)
listener.start()

# 鼠标点击时的行为
>>>>>>> mainline
def on_click(x, y, button, pressed):
    global clicked_position
    if pressed:
        clicked_position = (x, y)
<<<<<<< HEAD
        print('Recorded position: {0}'.format(clicked_position))
        return False  # Return False to stop the listener

def get_position():
    print('Move the mouse to the desired click position and then click the left mouse button.')
=======
        print('记录坐标: {0}'.format(clicked_position))
        return False  # 返回 False 来停止监听器

def get_position():
    print('将鼠标移动到想要点击的位置，然后点击鼠标左键。')
>>>>>>> mainline
    with MouseListener(on_click=on_click) as listener:
        listener.join()
    return clicked_position

def get_action():
<<<<<<< HEAD
    action_type = input("Enter action type (1: Click; 2: Key press): ")
    if action_type == "1":
        position = get_position()
        print('Clicked position: ', position)
        action_input = position
        hold_duration = 0
    elif action_type == "2":
        key_char = input("Enter the key to press: ")
        action_input = KeyCode(char=key_char)
        hold_choice = input("Press multiple times? (y/n): ")
        if hold_choice.lower() == 'y':
            hold_duration = int(input("How many times do you want to press it? "))
        else:
            hold_duration = 0
    else:
        print("Unknown action type. Please try again.")
        return None
    
    delay_seconds = int(input("Enter the delay time (in seconds) to the next action: "))
=======
    action_type = input("请输入动作类型（1：点击；2：按键）：")
    if action_type == "1":
        position = get_position()
        print('点击的位置是: ', position)
        action_input = position
        hold_duration = 0
    elif action_type == "2":
        key_char = input("请输入需要按的键：")
        action_input = KeyCode(char=key_char)
        hold_choice = input("需要按多次吗？(y/n)：")
        if hold_choice.lower() == 'y':
            hold_duration = int(input("你要按几把几次吧："))
        else:
            hold_duration = 0
    else:
        print("未知的动作类型。请重新输入。")
        return None
    
    delay_seconds = int(input("请输入动作到下一个动作的延迟时间（秒）："))
>>>>>>> mainline
    return {"type": action_type, "input": action_input, "delay": delay_seconds, "hold": hold_duration}

def get_actions(n):
    actions = []
    for i in range(n):
<<<<<<< HEAD
        print('Getting action {0}:'.format(i + 1))
=======
        print('获取第{0}个动作：'.format(i + 1))
>>>>>>> mainline
        action = get_action()
        if action is not None:
            actions.append(action)
    return actions

preset_actions = {
<<<<<<< HEAD
    '1': [
        {"type": "1", "input": None, "delay": 2, "hold": 0}, 
        {"type": "2", "input": KeyCode(char='y'), "delay": 2, "hold": 15},
        {"type": "1", "input": None, "delay": 2, "hold": 0},  
        {"type": "1", "input": None, "delay": 2, "hold": 0},  
        {"type": "2", "input": KeyCode(char='y'), "delay": 180, "hold": 5} 
    ],
    '2': [
        {"type": "1", "input": None, "delay": 2, "hold": 0},  
        {"type": "2", "input": Key.enter, "delay": 4, "hold": 0},  
        {"type": "1", "input": None, "delay": 310, "hold": 0},  
    ]
}

def get_preset_actions():
    print('Current available preset schemes (1,2):', ', '.join(preset_actions.keys()))
    preset_name = input('Please enter the name of the preset scheme you want to use:')
    if preset_name in preset_actions:
        actions = preset_actions[preset_name]
=======
    #挂草
    '1': [
        {"type": "1", "input": None, "delay": 2, "hold": 0},  # 鼠标点击
        {"type": "2", "input": KeyCode(char='y'), "delay": 2, "hold": 15},  # 按键
        {"type": "1", "input": None, "delay": 2, "hold": 0},  # 鼠标点击
        {"type": "1", "input": None, "delay": 2, "hold": 0},  # 鼠标点击
        {"type": "2", "input": KeyCode(char='y'), "delay": 180, "hold": 5}   # 按键
    ],
    #做药
    '2': [
        {"type": "1", "input": None, "delay": 2, "hold": 0},  # 鼠标点击
        {"type": "2", "input": Key.enter, "delay": 4, "hold": 0},  # 按键
        {"type": "1", "input": None, "delay": 310, "hold": 0},  # 鼠标点击
        
    ]

}

    


# 预设动作选择的函数
def get_preset_actions():
    print('当前可选预设方案(挂草1,做药2):', ', '.join(preset_actions.keys()))
    preset_name = input('请输入要使用的预设方案名称，如果不使用预设方案，请直接回车：')
    if preset_name in preset_actions:
        actions = preset_actions[preset_name]
        # 预设方案中的点击动作需要用户来指定点击的位置
>>>>>>> mainline
        for action in actions:
            if action["type"] == "1":
                action["input"] = get_position()
        return actions
    else:
        return None

preset = get_preset_actions()
if preset is not None:
    actions = preset
else:
<<<<<<< HEAD
    num_actions = int(input("Please enter the number of actions:"))
=======
    num_actions = int(input("请输入动作的数量："))
>>>>>>> mainline
    actions = get_actions(num_actions)

while True:
    if running:
        for action in actions:
            if action["type"] == "1":
<<<<<<< HEAD
                mouse.position = action["input"]
                time.sleep(0.1)
                mouse.click(Button.left, 1)
            elif action["type"] == "2":
=======
                # 将鼠标移动到点并点击
                mouse.position = action["input"]
                time.sleep(0.1)  # 避免过快移动导致的问题
                mouse.click(Button.left, 1)
            elif action["type"] == "2":
                # 重复按某个键
>>>>>>> mainline
                if action["hold"] > 0:
                    for i in range(action["hold"]):
                        keyboard.press(action["input"])
                        time.sleep(0.5)
                        keyboard.release(action["input"])
<<<<<<< HEAD
=======
                        i+=i                    
>>>>>>> mainline
                else:
                    keyboard.press(action["input"])
                    keyboard.release(action["input"])
            else:
<<<<<<< HEAD
                print("Unknown action type.")
                continue
            time.sleep(0.1)
=======
                print("未知的动作类型。")
                continue
            time.sleep(0.1)

            # 用户设置的延迟时间
>>>>>>> mainline
            for _ in range(action["delay"]):  
                if not running:
                    break
                time.sleep(1)
    else:
        time.sleep(0.1)
<<<<<<< HEAD

=======
>>>>>>> mainline
