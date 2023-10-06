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

    # Skills
    FOX_SPIRIT = "-"
    SHOW_DOWN = "1"
    DARK_FLARE = "g"
    LEAP = "z"
    SUDDEN_RAID = "w"
    DEATH_STAR = "a"
    WARRIOR = "f5"

    ERDA_FOUNTAIN = "c"
    ROPE  = "s"


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
                    if abs(d_x) > settings.move_tolerance * 10:
                        TripleJump().main()
                    elif settings.move_tolerance * 5 < abs(d_x) < settings.move_tolerance * 10:
                        DoubleJump().main()
                    elif abs(d_x) < settings.move_tolerance * 5:
                        time.sleep(0.05)
                    if settings.record_layout:
                        config.layout.add(*config.player_pos)
                    counter -= 1
                else:
                    key_up("left")
                    key_up("right")
                    d_y = point[1] - config.player_pos[1]
                    if abs(d_y) > settings.move_tolerance:
                        if d_y < 0:
                            if abs(d_y) < 0.12:
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


class Show_Down(Command):
    def main(self):
        press(Key.SHOW_DOWN)


class TripleJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        TripleJump().main()
        Show_Down().main()
        key_up(self.direction)
        time.sleep(0.4)


class DoubleJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        time.sleep(0.1)
        Show_Down().main()
        time.sleep(0.55)
        key_up(self.direction)


class StraightJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction)
        DoubleJump().main()
        Show_Down().main()
        time.sleep(0.4)



class Buff(Command):
    """Uses each of Kanna's buffs once. Uses 'Haku Reborn' whenever it is available."""

    def __init__(self):
        super().__init__(locals())
        self.buff_time = 0

    def main(self):
        now = time.time()
        if self.buff_time == 0 or now - self.buff_time > 1140:
            press(Key.WARRIOR, 3, 0.1, 0.001)
            self.buff_time = now


class UpJump(Command):
    def main(self):
        key_up("left"); key_up("right")
        time.sleep(0.05)
        press(Key.JUMP, 1, down_time = 0.156, up_time = 0.19)
        press(Key.LEAP, 1, down_time = 0.391, up_time = 0.1)


class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)


class ErdaFountain(Command):
    def main(self):
        key_down("down")
        press(Key.ERDA_FOUNTAIN, 4)
        key_up("down")


class ErdaShower(Command):
    def main(self):
        press(Key.ERDA_FOUNTAIN, 2)


class TripleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)


class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)


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


class DarkFlare(Command):
    def main(self):
        press(Key.DARK_FLARE, 3, 0.02, 0.02)


class SuddenRaid(Command):
    def main(self):
        press(Key.SUDDEN_RAID, 3, 0.05, 0.05)


class DeathStar(Command):
    def main(self):
        press(Key.DEATH_STAR, 3, 0.1, 0.1)


class SH2_POINT_1(Command):
    def main(self):
        key_down("right")
        time.sleep(0.125)
        key_up("right")
        press(Key.JUMP, 1, 0.109, 0.094)
        press(Key.JUMP, 1, 0.109, 0.032)
        time.sleep(0.015)
        press("left", 1, 0.110, 0.062)
        press(Key.SHOW_DOWN, 1, 0.094, 0.6)


class SH2_POINT_2(Command):
    def main(self):
        key_down("right")
        time.sleep(0.125)
        press(Key.JUMP, 1, 0.094, 0.094)
        press(Key.JUMP, 1, 0.140, 0.047)
        key_up("right")
        time.sleep(0.110)
        press(Key.SHOW_DOWN, 1, 0.109, 0.6)

class SH2_POINT_3(Command):
    def main(self):
        key_down("right")
        time.sleep(0.094)
        press(Key.JUMP, 1, 0.109, 0.172)
        press(Key.JUMP, 1, 0.125, 0.001)
        key_up("right")
        time.sleep(0.032)
        press(Key.SHOW_DOWN, 2, 0.1, 0.6)
        time.sleep(0.35)

class SH2_POINT_4(Command):
    def main(self):
        press("left", 1, 0.11, 0.001)
        DoubleJumpAttack("left").main()


class SH2_POINT_5(Command):
    def main(self):
        press("left", 1, 0.11, 0.001)
        DoubleJumpAttack("left").main()


class SH2_POINT_6(Command):
    def main(self):
        press("left", 1, 0.11, 0.001)
        DoubleJumpAttack("left").main()


class SH2_POINT_7(Command):
    def main(self):
        key_down("left")
        time.sleep(0.187)
        press("space", 1, 0.141, 0.109)
        press(Key.LEAP, 1, 0.235, 0.094)
        key_up("left")