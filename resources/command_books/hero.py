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

    ERDA_FOUNTAIN = "c"

    PUNCTURE = "1"
    RAGING_BELOW = "2"
    UPWARD_CHARGE = "z"
    RISING_RAGE = "w"
    WORLD_DREAVER = "3"
    BEAM_BLADE = "t"
    SOUL_BLADE="f2"


    RIGHT="right"
    LEFT="left"
    UP="up"


class UpJump(Command):

    def __init__(self, wait: float = 0):
        super().__init__(locals())
        self.wait = float(wait)
    def main(self):
        press(Key.UPWARD_CHARGE, 1, 0.1, 0.4)
        time.sleep(self.wait)


class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n=1, down_time=0.1, up_time=0.05)
        press(Key.JUMP, n=1, down_time=0.04, up_time=0.1)


class DownJump(Command):
    def __init__(self, wait: float = 0):
        super().__init__(locals())
        self.wait = float(wait)
    def main(self):
        key_down("down")
        key_down("down")
        press(Key.JUMP, n=3, down_time=0.01, up_time=0.001)
        key_up("down")
        key_up("down")
        time.sleep(self.wait)

class Move(Command):
    """Moves to a given position using the shortest path based on the current Layout.
    This is a general implementation and can be overriden by the Move class in your command books"""

    def __init__(self, x, y, max_steps=100):
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
                    if settings.move_tolerance * 10 <= abs(d_x) < settings.move_tolerance * 20:
                        DoubleJump().main()
                        counter -= 10
                    elif abs(d_x) < settings.move_tolerance * 10:
                        time.sleep(0.1)
                        counter -= 1
                    if settings.record_layout:
                        config.layout.add(*config.player_pos)
                else:
                    key_up("left")
                    key_up("right")
                    time.sleep(0.2)
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

    pass

class Rope(Command):
    def __init__(self, direction=None, wait=0):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction) if direction else None
        self.wait = float(wait)
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)
        if self.direction:
            press(self.direction, 2, 0.01, 0.01)
        time.sleep(self.wait)

class ErdaFountain(Command):
    def main(self):
        press(Key.ERDA_FOUNTAIN, 2, 0.1, 0.3)


def ms_sleep(time_ms: int):
    time.sleep(time_ms / 1000)
    return None


class JumpAttack(Command):
    def __init__(self, direction, wait):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.wait = float(wait)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        press(Key.RAGING_BELOW, 2, 0.01, 0.01)
        key_up(self.direction)
        time.sleep(0.4)
        time.sleep(self.wait)


class JumpPuncture(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        press(Key.PUNCTURE, 2, 0.01, 0.01)
        key_up(self.direction)
        time.sleep(0.7)

class Dash(Command):
    def __init__(self, direction, wait = 0):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.wait = float(wait)
    def main(self):
        key_down(self.direction)
        press(Key.DASH, 1, 0.1, 0.6)
        key_up(self.direction)
        time.sleep(self.wait)

class RisingRage(Command):
    def main(self):
        press(Key.RISING_RAGE, 1, 0.1, 0.01)


class WorldDreaver(Command):
    def __init__(self, wait = 0):
        super().__init__(locals())
        self.wait = float(wait)

    def main(self):
        press(Key.WORLD_DREAVER, 1, 0.1, 0.8)
        time.sleep(self.wait)


class BeamBlade(Command):
    def __init__(self, horizontal_direction=None, vertical_direction=None, wait = 0):
        super().__init__(locals())
        self.horizontal_direction = horizontal_direction
        self.vertical_direction = vertical_direction
        self.wait = float(wait)
    def main(self):
        if self.horizontal_direction:
            key_down(self.horizontal_direction)
        if self.vertical_direction:
            key_down(self.vertical_direction)
        press(Key.BEAM_BLADE, 1, 0.1, 0.01)
        if self.horizontal_direction:
            key_up(self.horizontal_direction)
        if self.vertical_direction:
            key_up(self.vertical_direction)

class SoulBlade(Command):
    def main(self):
        press(Key.SOUL_BLADE, 2, 0.1, 0.3)


class JumpBeamBladeOrRaging(Command):
    def __init__(self, direction, wait):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.wait = float(wait)
        self.flip = True

    def main(self):
        if self.flip:
            key_down(self.direction)
            DoubleJump().main()
            RisingRage().main()
            key_up(self.direction)
            time.sleep(0.4)
            time.sleep(self.wait)
        else:
            BeamBlade(horizontal_direction="up").main()
            time.sleep(0.5)
            key_down(self.direction)
            DoubleJump().main()
            press(Key.RAGING_BELOW, 2, 0.01, 0.01)
            key_up(self.direction)
            time.sleep(0.4)
            time.sleep(self.wait)
        self.flip = not self.flip