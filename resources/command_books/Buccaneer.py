"""A collection of all commands that a Kanna can use to interact with the game."""

from src.easymaple.common import config, settings, utils
import time
import math
from src.easymaple.routine.components import Command
from src.easymaple.common.vkeys import press, key_down, key_up


# List of key mappings
class Key:
    # Movement
    JUMP = 'space'
    DASH = '4'
    ROPE = "s"
    VORTEX = "d"

    ERDA_FOUNTAIN = "c"

    # Skills
    HOOK_BOMBER = "1"
    DICE = "insert"

    RIGHT="right"
    LEFT="left"
    UP="up"


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


def super_jump():
    key_down(Key.DASH)
    time.sleep(0.1)
    key_down(Key.JUMP)
    time.sleep(0.2)
    key_up(Key.DASH)
    key_up(Key.JUMP)

class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)


def up_jump():
    key_down("up")
    press(Key.JUMP, 1, down_time=0.05, up_time=0.01)
    press(Key.JUMP, 1, down_time=0.05, up_time=1.0)
    key_up("up")



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



class Buff(Command):
    """Uses each of Kanna's buffs once. Uses 'Haku Reborn' whenever it is available."""

    def __init__(self):
        super().__init__(locals())
        self.buff_time_180 = 0

    def main(self):
        now = time.time()
        if self.buff_time_180 == 0 or now - self.buff_time_180 > 200:
            press(Key.DICE, 3, 0.2, 0.2)
            self.buff_time_180 = time.time()
            
class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)

class ErdaFountain(Command):

    def main(self):
        key_down("down")
        press(Key.ERDA_FOUNTAIN, 4)
        key_up("down")

def ms_sleep(time_ms: int):
    time.sleep(time_ms / 1000)
    return None

class LibrarySimple(Command):

    def __init__(self):
        super().__init__(locals())

    def main(self):
        key_down(Key.LEFT)
        key_down(Key.DASH)
        key_down(Key.JUMP)
        key_up(Key.LEFT)
        ms_sleep(15)
        key_up(Key.DASH)
        ms_sleep(32)
        key_up(Key.JUMP)
        ms_sleep(1062)
        key_down(Key.DASH)
        key_down(Key.JUMP)
        ms_sleep(16)
        key_up(Key.DASH)
        ms_sleep(31)
        key_up(Key.JUMP)
        ms_sleep(500)

        key_down(Key.RIGHT)
        ms_sleep(50)
        key_up(Key.RIGHT)

        key_down(Key.RIGHT)
        ms_sleep(50)
        key_up(Key.RIGHT)

        ms_sleep(500)
        key_down(Key.RIGHT)
        ms_sleep(50)
        key_up(Key.RIGHT)
        key_down(Key.RIGHT)
        ms_sleep(50)
        key_up(Key.RIGHT)
        key_down(Key.RIGHT)
        ms_sleep(47)
        key_up(Key.RIGHT)
        key_down(Key.RIGHT)
        ms_sleep(47)
        key_up(Key.RIGHT)

        ms_sleep(497)

        key_down(Key.DASH)
        key_down(Key.JUMP)
        ms_sleep(16)
        key_up(Key.DASH)
        ms_sleep(31)
        key_up(Key.JUMP)

        ms_sleep(1047)

        key_down(Key.DASH)
        key_down(Key.JUMP)
        ms_sleep(15)
        key_up(Key.DASH)
        ms_sleep(32)
        key_up(Key.JUMP)

        ms_sleep(437)
        key_down(Key.LEFT)
        ms_sleep(47)
        key_up(Key.LEFT)
        key_down(Key.LEFT)
        ms_sleep(47)
        key_up(Key.LEFT)

        ms_sleep(609)
        key_down(Key.ROPE)
        ms_sleep(110)
        key_up(Key.ROPE)

        ms_sleep(1700)
        key_down(Key.LEFT)
        ms_sleep(47)
        key_up(Key.LEFT)
        ms_sleep(150)


class LibSimple2(Command):
    def __init__(self):
        super().__init__(locals())


    def main(self):
        key_down(Key.RIGHT)
        ms_sleep(300)
        key_up(Key.RIGHT)

        key_down(Key.LEFT)
        ms_sleep(20)
        key_up(Key.LEFT)


        key_down(Key.LEFT)
        key_down(Key.LEFT)
        ms_sleep(25)
        key_down(Key.VORTEX)
        ms_sleep(25)
        key_up(Key.LEFT)
        key_up(Key.VORTEX)
        ms_sleep(710)

        key_down(Key.UP)
        key_down(Key.UP)
        ms_sleep(25)
        key_down(Key.VORTEX)
        ms_sleep(25)
        key_up(Key.UP)
        key_up(Key.VORTEX)
        ms_sleep(1200)

        key_down(Key.DASH)
        key_down(Key.JUMP)
        ms_sleep(16)
        key_up(Key.DASH)
        ms_sleep(31)
        key_up(Key.JUMP)

        ms_sleep(1300)
        key_down(Key.RIGHT)
        ms_sleep(47)
        key_up(Key.RIGHT)
        key_down(Key.RIGHT)
        ms_sleep(47)
        key_up(Key.RIGHT)

        ms_sleep(297)

        key_down(Key.DASH)
        key_down(Key.JUMP)
        ms_sleep(16)
        key_up(Key.DASH)
        ms_sleep(31)
        key_up(Key.JUMP)

        ms_sleep(1047)

        key_down(Key.DASH)
        key_down(Key.JUMP)
        ms_sleep(15)
        key_up(Key.DASH)
        ms_sleep(32)
        key_up(Key.JUMP)

        ms_sleep(437)
        key_down(Key.LEFT)
        ms_sleep(47)
        key_up(Key.LEFT)
        key_down(Key.LEFT)
        ms_sleep(47)
        key_up(Key.LEFT)

        ms_sleep(609)
        key_down(Key.ROPE)
        ms_sleep(110)
        key_up(Key.ROPE)

        ms_sleep(1700)
        key_down(Key.LEFT)
        ms_sleep(47)
        key_up(Key.LEFT)
        ms_sleep(150)


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

class UpJump(Command):
    def main(self):
        key_down("up")
        press(Key.JUMP, 1, down_time = 0.05, up_time = 0.01)
        press(Key.JUMP, 1, down_time = 0.05, up_time = 1.0)
        key_up("up")


