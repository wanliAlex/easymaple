"""A collection of all commands that a Hero can use to interact with the game."""

import cv2
import pyautogui
import pytesseract
import pygetwindow as gw
from src.easymaple.common import config, settings, utils
import time
import math
import threading
from src.easymaple.routine.components import Command
from src.easymaple.common.vkeys import press, key_down, key_up


template_tl = cv2.imread('assets/tl_hayato.png', 0)
template_br = cv2.imread('assets/br_hayato.png', 0)



class GameImageProcessor:
    def __init__(self, window_title="MapleStory"):
        self.window = self.locate_window(window_title)
    
    def locate_window(self, window_title):
        try:
            window = gw.getWindowsWithTitle(window_title)[0]
            return window
        except IndexError:
            print(f"Window titled '{window_title}' not found")
            exit()

    def find_hayato_se(self):
        try:
            x, y, w, h = self.window.left, self.window.top, self.window.width, self.window.height
            screenshot = pyautogui.screenshot(region=(x, y, w, h))
            screenshot.save("maplewindow.png")
            
            game_screenshot = cv2.imread("maplewindow.png")
            game_gray = cv2.cvtColor(game_screenshot, cv2.COLOR_BGR2GRAY)

            res_tl = cv2.matchTemplate(game_gray, template_tl, cv2.TM_CCOEFF_NORMED)
            res_br = cv2.matchTemplate(game_gray, template_br, cv2.TM_CCOEFF_NORMED)
            
            _, _, _, max_loc_tl = cv2.minMaxLoc(res_tl)
            _, _, _, max_loc_br = cv2.minMaxLoc(res_br)
            top_left = max_loc_tl
            bottom_right = (max_loc_br[0] + template_br.shape[1], max_loc_br[1] + template_br.shape[0])
            
            top_left1 = (top_left[0] + 38, top_left[1] + 56)
            bottom_right1 = (bottom_right[0] - 80, bottom_right[1] - 10)
            
            matched_region = game_screenshot[top_left1[1]:bottom_right1[1], top_left1[0]:bottom_right1[0]]
            if matched_region.size == 0:
                print("No matched region found, skipping resize.")
                return 500  # 或者其他合适的默认值或错误处理

            # Resize and threshold the image to enhance OCR accuracy
            scale_factor = 4
            enlarged_image = cv2.resize(matched_region, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_LINEAR)
            gray = cv2.cvtColor(enlarged_image, cv2.COLOR_BGR2GRAY)
            _, processed_image = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Use Tesseract to extract text, with configuration for OCR processing
            text = pytesseract.image_to_string(processed_image, config='--psm 6')

            cv2.imwrite('hayato_SE.png', processed_image)
            return int(text)
        except Exception as e:
            print(f"An error occurred: {e}")
            return 500  # 在遇到任何异常时返回500

# Example usage


# List of key mappings
class Key:
    # Movement
    RIGHT_ARROW = 'right'
    LEFT_ARROW = 'left'
    UP_ARROW = 'up'
    DOWN_ARROR = 'down'
    JUMP = 'space'
    UPWAIRD_CHARGE  = "s"  #up jump skill
    ROPE = 'alt'

    RUSH = 'd'
    SURGING_BLADE = "w"
    
    # Skills[Buffs]
    GREEN_POT = "="
    YELLO_POT = "-"

    # Skills[Damage:attack]
    PHANTOM_BLADE = "c"
    SANRENZAN = "a"
    ZANKOU = '2'
    
    
    FALCON_HONOR = "ctrl"
    INSTANCE_SLICE = "r"

    
    
    # Skills [Placement]
    ERDA_FOUNTAIN = "end"
    JIANSHEN = "1"
    SENGOKU ="3"

#########################
#       Commands        #
#########################

def long_jump():

    press(Key.JUMP, n = 1, down_time = 0.125, up_time = 0.1)
    press(Key.JUMP, n=1, down_time=0.14, up_time=0.09)
    press(Key.JUMP, n=1, down_time=0.18, up_time=0.01)

def short_jump():

    press(Key.JUMP, n=1, down_time=0.1, up_time=0.25)
    press(Key.JUMP, n=1, down_time=0.14, up_time=0.01)



def step(direction, target):
    """
    Performs one movement step in the given DIRECTION towards TARGET.
    Should not press any arrow keys, as those are handled by Auto Maple.
    """
    pass


class Move(Command):
    """Moves to a given position using the shortest path based on the current Layout.
    This is a general implementation and can be overriden by the Move class in your command books"""

    def __init__(self, x, y, max_steps=15):
        super().__init__(locals())
        self.target = (float(x), float(y))
        self.max_steps = settings.validate_nonnegative_int(max_steps)
        self.prev_direction = ''

    def _new_direction(self, new):
        key_down(new)
        if self.prev_direction and self.prev_direction != new:
            key_up(self.prev_direction)
        self.prev_direction = new

    def main(self):
        counter = self.max_steps
        path = config.layout.shortest_path(config.player_pos, self.target)
        for i, point in enumerate(path):
            toggle = True
            self.prev_direction = ''
            local_error = utils.distance(config.player_pos, point)
            global_error = utils.distance(config.player_pos, self.target)
            while config.enabled and counter > 0 and \
                    local_error > settings.move_tolerance and \
                    global_error > settings.move_tolerance:
                d_x = point[0] - config.player_pos[0]
                if abs(d_x) > settings.move_tolerance / math.sqrt(2):
                    if d_x < 0:
                        key = 'left'
                    else:
                        key = 'right'
                    self._new_direction(key)
                    if abs(d_x) > settings.move_tolerance * 5:
                        DoubleJump().main()
                    if settings.record_layout:
                        config.layout.add(*config.player_pos)
                    counter -= 1
                    if i < len(path) - 1:
                        time.sleep(0.15)
                else:
                    d_y = point[1] - config.player_pos[1]
                    if abs(d_y) > settings.move_tolerance / math.sqrt(2):
                        if d_y < 0:
                            if abs(d_y) < 0.1:
                                UpJump().main()
                                time.sleep(0.5)
                            else:
                                Rope().main()
                                time.sleep(2)
                        else:
                            key_down('down')
                            time.sleep(0.05)
                            press(Key.JUMP, 3, down_time=0.1)
                            key_up('down')
                            time.sleep(0.5)
                        if settings.record_layout:
                            config.layout.add(*config.player_pos)
                        if i < len(path) - 1:
                            time.sleep(0.05)
                    counter -= 1
                local_error = utils.distance(config.player_pos, point)
                global_error = utils.distance(config.player_pos, self.target)
                toggle = not toggle
            if self.prev_direction:
                key_up(self.prev_direction)



class Adjust(Command):
    """Fine-tunes player position using small movements."""

    def __init__(self, x, y, max_steps=5):
        super().__init__(locals())
        self.target = (float(x), float(y))
        self.max_steps = settings.validate_nonnegative_int(max_steps)

    def main(self):
        counter = self.max_steps
        error = utils.distance(config.player_pos, self.target)
        while config.enabled and counter > 0 and error > settings.adjust_tolerance:
            d_x = self.target[0] - config.player_pos[0]
            d_y = self.target[1] - config.player_pos[1]
            threshold = settings.adjust_tolerance / math.sqrt(2)
            if abs(d_x) > settings.adjust_tolerance and counter > self.max_steps // 2:
                walk_counter = 0
                if d_x < 0:
                    key_down('left')
                    while config.enabled and d_x < -1.5 * threshold and walk_counter < 60:
                        time.sleep(0.05)
                        walk_counter += 1
                        d_x = self.target[0] - config.player_pos[0]
                    key_up('left')
                else:
                    key_down('right')
                    while config.enabled and d_x > 1.5 * threshold and walk_counter < 60:
                        time.sleep(0.05)
                        walk_counter += 1
                        d_x = self.target[0] - config.player_pos[0]
                    key_up('right')
                counter -= 1
            else:
                key_up("left")
                key_up("right")
                time.sleep(0.5)
                if abs(d_y) > threshold:
                    if d_y < 0:
                        if abs(d_y) < 0.1:
                            UpJump().main()
                            time.sleep(0.5)
                        else:
                            Rope().main()
                            time.sleep(2)
                    else:
                        key_down('down')
                        time.sleep(0.05)
                        press(Key.JUMP, 3, down_time=0.1)
                        key_up('down')
                        time.sleep(0.5)
                counter -= 1
            error = utils.distance(config.player_pos, self.target)




class JianShen(Command):

    def main(self):
        press(Key.JIANSHEN)

class SenGoKu(Command):

    def main(self):
        press(Key.SENGOKU)

class Sanrenzan(Command):
    def __init__(self,repetitions=1):
        super().__init__(locals())
        self.repetitions = int(repetitions)
    def main(self):
        for _ in range (self.repetitions):
            press(Key.SANRENZAN,1,0.1,0.1)


class ErdaFountain(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction,1)
        press(Key.ERDA_FOUNTAIN,2)



class Buff(Command):
    pass
    # def __init__(self):
    #     super().__init__(locals())
    #     self.lock = threading.Lock()
        
        
    #     self.buff_time_120 = 0
    #     '''
    #     self.monster_park_pot_30mins = 0
    #     self.buff_time_180 = 0
    #     '''

    # def main(self):
    #     buffs_120 = [Key.SENGOKU,Key.JIANSHEN]
    #     now = time.time()
    #     '''
    #     buffs_1800 = [Key.GREEN_POT, Key.YELLO_POT]
    #     buffs_180 = [Key.DICE, Key.SHAPR_EYE, Key.COMBAT_ORDER]
    #     '''
        
    #     '''
    #     if self.monster_park_pot_30mins == 0 or now - self.monster_park_pot_30mins > 1800:
    #         for key in buffs_1800:
    #             press(key,1,down_time=0.5,up_time=0.3)
    #         self.monster_park_pot_30mins = now
    #     '''
    #     if self.buff_time_120 == 0 or now - self.buff_time_120 > 120:            
    #         for key in buffs_120:
    #             press(key, 3, up_time=0.3)
    #         self.buff_time_120 = now
    #     '''
    #     if self.buff_time_180 == 0 or now - self.buff_time_180 > 180:            
    #         for key in buffs_180:
    #             press(key, 3, up_time=0.4)
    #         self.buff_time_180 = now
    #         time.sleep(1)
    #     '''

class UpJump(Command):
    def main(self):
        press(Key.UPWAIRD_CHARGE)



class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)

class ShortRope(Command):
    def main(self):
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)

class will(Command):
    def main(self):
        press(Key.WILL, 1, up_time = 0.3)


class Move_right(Command):
    
    def __init__(self,key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)
    def main(self):
        press(Key.RIGHT_ARROW,n=1,down_time=self.key_down_time,up_time=0.01)

class Move_left(Command):
    
    def __init__(self,key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)
    def main(self):
        press(Key.LEFT_ARROW,n=1,down_time=self.key_down_time,up_time=0.01)



class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.072, up_time = 0.01)
        press(Key.JUMP, n = 1, down_time=0.064, up_time=0.01)

class HighDoubleJump(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        
    def main(self):
        press(self.direction)
        press(Key.JUMP, n = 1, down_time = 0.320, up_time = 0.0)
        press(Key.JUMP, n = 1, down_time=0.95, up_time=0.0)

class DownJump(Command):
    def __init__(self, wait_time = 0.3):
        super().__init__(locals())
        self.wait_time = float(wait_time)

    def main(self):
        key_down("down")
        time.sleep(0.1)
        press(Key.JUMP, 3, 0.01, up_time =0.01)
        time.sleep(self.wait_time / 2.0)
        key_up("down")
        time.sleep(self.wait_time / 2.0)


class FalconHonor(Command):
    def main(self):
        press(Key.FALCON_HONOR, 2)

class PhantomBlade(Command):
    def main(self):
        press(Key.PHANTOM_BLADE, 2)

class InstanceSlice(Command):
    def main(self):
        press(Key.INSTANCE_SLICE)


class SurgingBlade (Command):
    def __init__(self, direction,repetitions=1):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.repetitions = int(repetitions)
    def main(self):
        for _ in range(self.repetitions):
            press(self.direction)
            press(Key.SURGING_BLADE,n = 1, down_time = 0.054, up_time = 0.016)



class Rush(Command):
    def __init__(self,direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    
    def main(self):
        press(self.direction)
        press(Key.RUSH,2)

class RushToFront(Command):
    def __init__(self):
        super().__init__(locals())

    
    def main(self):

        press(Key.RUSH,2)

class RushSurge(Command):
    def __init__(self,direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    
    def main(self):
        press(self.direction)
        press(Key.RUSH,1)
        press(Key.SURGING_BLADE,1)


class Move_Up(Command):
    
    def __init__(self,key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)
    def main(self):
        press(Key.UP_ARROW,n=1,down_time=self.key_down_time,up_time=0.01)






FH_CD = 0
IS_CD = 0
JIANSHEN_CD = -120
SENGOKU_CD = -120

class Trinity_Attack(Command):
    def __init__(self, wait: float = 0.5):
        super().__init__(locals())
        self.wait = float(wait)


    def main(self):
        global FH_CD  
        global IS_CD 
        now = time.perf_counter()
        hayato_SE = GameImageProcessor().find_hayato_se()
        if hayato_SE >= 800:
            PhantomBlade().main()
        elif hayato_SE < 200:
            press(Key.ZANKOU, n=2)
            time.sleep(4)
        else:
            if now - FH_CD > 9:
                FalconHonor().main()
                FH_CD = now
                
            elif now - IS_CD > 11:
                 
                press(Key.INSTANCE_SLICE, n=2)
                IS_CD = now
            else:
                PhantomBlade().main()
        time.sleep(self.wait)

class Move_Up(Command):
    def main(self):
        press(Key.UP_ARROW, 3)


class Pick_Up_Money(Command):
    def __init__(self):
        super().__init__(locals())

    def main(self):
        global JIANSHEN_CD 
        global SENGOKU_CD 
        now = time.perf_counter()
        if now - JIANSHEN_CD  > 120:
            
            JianShen().main()
            JIANSHEN_CD = now
            time.sleep(0.3)
            
        elif now - SENGOKU_CD > 120:
            
            SenGoKu().main()
            SENGOKU_CD = now
            time.sleep(0.3)
            


class Find_portal_ECRB1(Command):
    target_point1 = (0.294,0.130) 
    target_point2 = (0.701, 0.130)

    def main(self):
        for _ in range(15):
            x_distance = config.player_pos[0] - self.target_point1[0]
            direction = "right" if x_distance < 0 else "left"
            press(direction, 1, self._calculate_move_time(abs(x_distance)))
            press("up", 1, 0.01)
            if utils.distance(self.target_point2, config.player_pos) < 0.1:
                break

    def _calculate_move_time(self, distance):
            if distance < 0.005:
                return max(distance * 3.5, 0.01)
            else:
                return max(distance * 8, 0.04)




 


           


