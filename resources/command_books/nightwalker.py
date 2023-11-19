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
    QUINTUPLE_STAR = "1"
    DARK_OMEN = "w"
    SHADOW_BITE = "g"
    DARK_SERVENT = "f"

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
                        time.sleep(0.25)
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



class TripleJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        TripleJump().main()
        time.sleep(0.5)
        press(Key.QUINTUPLE_STAR, 1, 0.1, 0.1)
        key_up(self.direction)
        time.sleep(0.1)


class DoubleJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        time.sleep(0.15)
        press(Key.QUINTUPLE_STAR, 1, 0.1, 0.1)
        time.sleep(0.35)
        key_up(self.direction)


class StraightJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction)
        DoubleJump().main()
        press(Key.QUINTUPLE_STAR, 1, 0.1, 0.1)
        time.sleep(0.1)



class Buff(Command):
    def __init__(self):
        super().__init__(locals())
        self.buff_time = 0

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
        press(Key.ROPE, 1, up_time = 0.3)

class DarkServant(Command):
    def main(self):
        press(Key.DARK_SERVENT, 1, 0.1, 0.2)
        time.sleep(0.3)


class ErdaFountain(Command):
    def __init__(self, press_top: bool = False, toggled: bool = True):
        super().__init__(locals())
        self.press_top = bool(press_top)
        self.toggled = bool(toggled)

    def main(self):
        if self.toggled:
            press(Key.ERDA_FOUNTAIN, 4)
            time.sleep(0.1)
        else:
            if self.press_top:
                key_down("up")
            key_down("down")
            press(Key.ERDA_FOUNTAIN, 4)
            key_up("down")
            if self.press_top:
                key_up("up")


class TripleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)


class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.086)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.1)


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


class DarkOmen(Command):
    def main(self):
        press(Key.DARK_OMEN, 2, 0.1, 0.05)


class DownJump(Command):
    def main(self):
        key_down("down")
        press(Key.JUMP, 2, 0.1, 0.05)


class CF3_RightTop(Command):
    _target_point = (0.871, 0.320)
    def main(self):
        key_down("down")
        press(Key.JUMP, 2, 0.2, 0.05)
        press("left", 2, 0.02)
        key_up("down")
        for i in range(100):
            if abs(self._target_point[1] - config.player_pos[1]) < 0.01:
                break
            else:
                time.sleep(0.02)


class CF3_LeftBot(Command):
    _target_point = (0.25, 0.163)
    def main(self):
        key_up("left")
        key_up("right")
        time.sleep(0.2)
        key_down("up")
        press(Key.JUMP, 1, down_time=0.1, up_time=0.1)
        press(Key.JUMP, 1, down_time=0.05, up_time=0.5)
        key_up("up")
        press("right", 2, 0.02)
        for i in range(100):
            if abs(self._target_point[1] - config.player_pos[1]) < 0.01:
                break
            else:
                time.sleep(0.02)



class PD2_YaJian(Command):
    erda_cd = 53
    shadow_bite_cd = 11.5
    tick = 0.5

    def __init__(self):
        super().__init__(locals())
        self.erda_time = 0
        self.shadow_bite_time = 0

    def main(self):
        now = time.time()
        if self.erda_time == 0 or now - self.erda_time > self.erda_cd:
            self.place_erda()
            self.erda_time = time.time()

        now = time.time()
        if self.shadow_bite_time == 0 or now - self.shadow_bite_cd > self.shadow_bite_cd:
            self.shadow_bite()
            self.shadow_bite_time = time.time()

        time.sleep(self.tick)

    @staticmethod
    def place_erda():
        press(Key.DARK_SERVENT, 1, 0.2, 0.5)
        press(Key.ROPE, 1, 0.1, 2.1)
        ErdaFountain().main()
        press(Key.DARK_SERVENT, 1, 0.1, 0.01)
        time.sleep(0.3)

    @staticmethod
    def shadow_bite():
        press(Key.SHADOW_BITE, 1, 0.1)




