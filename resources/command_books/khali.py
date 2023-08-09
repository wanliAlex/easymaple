"""A collection of all commands that a Kanna can use to interact with the game."""

from src.easymaple.common import config, settings, utils
import time
import math
from src.easymaple.routine.components import Command
from src.easymaple.common.vkeys import press, key_down, key_up
from typing import Optional


# List of key mappings
class Key:
    # Movement
    JUMP = 'space'

    # Skills
    FLURRY = "1"
    CRESCENTUM = "2"
    INSANITY = "4"
    SPLIT = "3"
    SWEEP = "a"
    BLOSSOM = "w"

    ERDA_FOUNTAIN = "c"
    ROPE = "s"


#########################
#       Commands        #
#########################


# JUMP PART

def long_jump():
    press(Key.JUMP, n=1, down_time=0.125, up_time=0.1)
    press(Key.JUMP, n=1, down_time=0.14, up_time=0.09)
    press(Key.JUMP, n=1, down_time=0.18, up_time=0.01)


def short_jump_distance():
    press(Key.JUMP, n=1, down_time=0.110, up_time=0.437)
    press(Key.JUMP, n=1, down_time=0.110, up_time=0.271)


def step(direction, target):
    """
    Performs one movement step in the given DIRECTION towards TARGET.
    Should not press any arrow keys, as those are handled by Auto Maple.
    """
    pass


class Move(Command):
    """Moves to a given position using the shortest path based on the current Layout.
    This is a general implementation and can be overriden by the Move class in your command books"""

    def __init__(self, x, y, max_steps=10):
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
                if abs(d_x) > settings.move_tolerance:
                    if d_x < 0:
                        key = 'left'
                    else:
                        key = 'right'
                    self._new_direction(key)
                    if abs(d_x) > settings.move_tolerance * 5:
                        DoubleJump().main()
                    elif abs(d_x) > settings.move_tolerance * 3.5 and abs(d_x) < settings.move_tolerance * 5:
                        short_jump_distance()
                    elif abs(d_x) < settings.move_tolerance * 3.5:
                        time.sleep(0.05)
                    if settings.record_layout:
                        config.layout.add(*config.player_pos)
                    counter -= 1
                else:
                    key_up("left")
                    key_up("right")
                    time.sleep(0.5)
                    d_y = point[1] - config.player_pos[1]
                    if abs(d_y) > settings.move_tolerance:
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
                    counter -= 4
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
                if abs(d_y) > 0.02:
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


class UpJump(Command):
    def main(self):
        key_down("up")
        press(Key.JUMP, 1, down_time=0.05, up_time=0.01)
        press(Key.JUMP, 1, down_time=0.05, up_time=1.0)
        key_up("up")


class Furry(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = str(direction)

    def main(self):
        press(self.direction, 1, 0.05, 0.05)
        press(Key.FLURRY, 2, 0.1, 0.1)


class JumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)

    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        Furry().main()
        key_up(self.direction)
        time.sleep(0.4)


class Buff(Command):
    """Uses each of Kanna's buffs once. Uses 'Haku Reborn' whenever it is available."""

    def __init__(self):
        super().__init__(locals())
        self.haku_time = 0
        self.buff_time_120 = 0
        self.buff_time_180 = 0

    def main(self):
        pass


class UpJump(Command):
    def main(self):
        key_down("up")
        press(Key.JUMP, 1, down_time=0.05, up_time=0.01)
        press(Key.JUMP, 1, down_time=0.05, up_time=1.0)
        key_up("up")


class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time=0.3)


class ErdaFountain(Command):

    def main(self):
        key_down("down")
        press(Key.ERDA_FOUNTAIN, 4)
        key_up("down")


class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n=1, down_time=0.094, up_time=0.046)
        press(Key.JUMP, n=1, down_time=0.141, up_time=0.11)


class DownJump(Command):
    def __init__(self, wait_time=0.3):
        super().__init__(locals())
        self.wait_time = float(wait_time)

    def main(self):
        key_down("down")
        time.sleep(0.1)
        press(Key.JUMP, 3, 0.01, up_time=0.01)
        time.sleep(self.wait_time / 2.0)
        key_up("down")
        time.sleep(self.wait_time / 2.0)


class Insanity(Command):
    def __init__(self, repetition: int = 3, direction_1: Optional[str] = None, direction_2: Optional[str] = None,
                 direction_3: Optional[str] = None, reset: bool = True):
        super().__init__(locals())
        self.repetition = int(repetition)
        self.direction_1 = str(direction_1)
        self.direction_2 = str(direction_2)
        self.direction_3 = str(direction_3)
        self.reset = bool(reset)

    def main(self):
        direction_list = [self.direction_1, self.direction_2, self.direction_3]
        for i in range(self.repetition):
            direction = direction_list[i]
            if direction:
                key_down(direction)
            press(Key.INSANITY, 3, 0.02, 0.05)
            if direction:
                key_up(direction)
        if self.reset:
            press(Key.CRESCENTUM, 4, 0.05, 0.05)


class SHInsanity(Command):
    def __init__(self):
        super().__init__(locals())
        self.repetition = 3

    def main(self):
        direction_list = ["up", "right", "right"]
        press("left", 1, 0.08, 0.05)
        for i in range(self.repetition):

            direction = direction_list[i]
            if direction:
                key_down(direction)

            press(Key.INSANITY, 3, 0.02, 0.06)

            if direction:
                key_up(direction)

            if i == 0:
                time.sleep(0.15)
                press(Key.SWEEP, 2, 0.1, 0.1)
                time.sleep(0.10)


class SHJump(Command):

    def main(self):
        key_down("right")
        time.sleep(0.078)
        press(Key.JUMP, 1, 0.109, 0.500)
        press(Key.JUMP, 1, 0.125, 0.360)
        key_up("right")
        time.sleep(0.109)
        key_down("left")
        time.sleep(0.125)
        press(Key.JUMP, 1, 0.088, 0.868)
        key_up("left")


class ShortJump(Command):

    def main(self):
        key_up("left")
        key_up("right")
        time.sleep(0.3)
        press(Key.JUMP, 1, 0.109, 0.150)


class short_jump(Command):
    def main(self):
        press(Key.JUMP, n=1, down_time=0.110, up_time=0.437)
        press(Key.JUMP, n=1, down_time=0.110, up_time=0.047)
