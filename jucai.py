import time
from pynput.mouse import Button, Controller as MouseController, Listener as MouseListener
from pynput.keyboard import Controller as KeyboardController, Listener as KeyboardListener, Key, KeyCode

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
def on_click(x, y, button, pressed):
    global clicked_position
    if pressed:
        clicked_position = (x, y)
        print('Recorded position: {0}'.format(clicked_position))
        return False  # Return False to stop the listener

def get_position():
    print('Move the mouse to the desired click position and then click the left mouse button.')
    with MouseListener(on_click=on_click) as listener:
        listener.join()
    return clicked_position

def get_action():
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
    return {"type": action_type, "input": action_input, "delay": delay_seconds, "hold": hold_duration}

def get_actions(n):
    actions = []
    for i in range(n):
        print('Getting action {0}:'.format(i + 1))
        action = get_action()
        if action is not None:
            actions.append(action)
    return actions

preset_actions = {
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
    num_actions = int(input("Please enter the number of actions:"))
    actions = get_actions(num_actions)

while True:
    if running:
        for action in actions:
            if action["type"] == "1":
                mouse.position = action["input"]
                time.sleep(0.1)
                mouse.click(Button.left, 1)
            elif action["type"] == "2":
                if action["hold"] > 0:
                    for i in range(action["hold"]):
                        keyboard.press(action["input"])
                        time.sleep(0.5)
                        keyboard.release(action["input"])
                else:
                    keyboard.press(action["input"])
                    keyboard.release(action["input"])
            else:
                print("Unknown action type.")
                continue
            time.sleep(0.1)
            for _ in range(action["delay"]):  
                if not running:
                    break
                time.sleep(1)
    else:
        time.sleep(0.1)
