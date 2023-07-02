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
    UPWAIRD_CHARGE  = "s"  #up jump skill
    ROPE = 'alt'
    
    # Skills[Buffs]
    
    
    
    # Skills[Damage:attack]
    
    PUNCTURE = "r"
    RAGING_BLOW = "a"
    BEAM_BLADE = "w"
    
    # Skills [Placement]
    ERDA_FOUNTAIN = "end"
    BURNING_BLADE = "1"
    WILL ="page down"

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


class Puncture(Command):
    def main(self):
        press(Key.PUNCTURE)

class RagingBlow(Command):
    def main(self):
        press(Key.RAGING_BLOW,n = 1, down_time = 0.094, up_time = 0.046)

class BeamBlade(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_arrows(direction)
    def main(self):
        key_down(self.direction)
        press(Key.BEAM_BLADE,n = 1, down_time = 0.094, up_time = 0.046)
        key_up(self.direction)

class JumpBeamBlade(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction)
        press(Key.JUMP)
        BeamBlade().main()
        time.sleep(0.35)

class JumpPuncture (Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    
    def main(self):
        press(self.direction)
        DoubleJump().main()
        Puncture().main()
        time.sleep(0.7)


class JumpRagingBlow (Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    
    def main(self):
        press(self.direction)
        DoubleJump().main()
        RagingBlow().main()
        time.sleep(0.335)

class BurningBlade(Command):
    def main(self):
        press(Key.BURNING_BLADE,4)
        time.sleep(1)
        press(Key.BURNING_BLADE,4)

class Buff(Command):    
    pass

class UpJump(Command):
    def main(self):
        press(Key.UPWAIRD_CHARGE)

class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)

class will(Command):
    def main(self):
        press(Key.WILL, 1, up_time = 0.3)

class ErdaFountain(Command):

    def main(self):
        key_down("down")
        press(Key.ERDA_FOUNTAIN, 4)
        key_up("down")

class ErdaShower(Command):

    def main(self):
        press(Key.ERDA_FOUNTAIN, 2)

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