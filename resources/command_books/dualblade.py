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
    FINAL_CUT = "3"
    BLADE_FURY = "1"
    PHANTOM_BLOW = "2"
    SUDDEN_RAID = "w"
    BLADE_TORNADO = "f"
    BOD = "g"
    DOUBLE_JUMP = "n"

    ERDA_FOUNTAIN = "c"

    BLADE_ASCENSION = "z"

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
                    if abs(d_x) > settings.move_tolerance * 10:
                        TripleJump().main()
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
                    while config.enabled and d_x < -1.5 * threshold and walk_counter < 30:
                        time.sleep(0.05)
                        walk_counter += 1
                        d_x = self.target[0] - config.player_pos[0]
                    key_up('left')
                else:
                    key_down('right')
                    while config.enabled and d_x > 1.5 * threshold and walk_counter < 30:
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
        self.haku_time = 0
        self.buff_time = 0

    def main(self):
        buffs = [ ]
        now = time.time()
       #if self.haku_time == 0 or now - self.haku_time > 490:
       #     press(Key.HAKU, 2)
       #     press(Key.AKATSUKI_WARRIOR, 2)
       #     self.haku_time = now
        if self.buff_time == 0 or now - self.buff_time > settings.buff_cooldown:
            pass
            for key in buffs:
                press(key, 3, up_time=0.3)
            self.buff_time = now

class UpJump(Command):
    def main(self):
        key_down("up")
        press(Key.JUMP, 1, down_time = 0.05, up_time = 0.05)
        press(Key.BLADE_ASCENSION, 1, down_time = 0.1, up_time = 0.3)
        key_up("up")



class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)



class Phantom_Blow(Command):

    def __init__(self, direction, attacks=2, repetitions=1):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.attacks = int(attacks)
        self.repetitions = int(repetitions)

    def main(self):
        time.sleep(0.05)
        key_down(self.direction)
        time.sleep(0.05)
        if config.stage_fright and utils.bernoulli(0.7):
            time.sleep(utils.rand_float(0.1, 0.3))
        for _ in range(self.repetitions):
            press(Key.PHANTOM_BLOW, self.attacks, up_time=0.05)
        key_up(self.direction)
        if self.attacks > 2:
            time.sleep(0.3)
        else:
            time.sleep(0.2)



class Blade_Fury(Command):
    """Uses 'Tengu Strike' once."""

    def main(self):
        press(Key.BLADE_FURY, 1, up_time=0.05)


class BOD(Command):

    def main(self):
        press(Key.BOD, 2)



class Blade_Tornado(Command):
    """
    Places 'Lucid Soul Summon' in a given direction, or towards the center of the map if
    no direction is specified.
    """

    def __init__(self, direction=None):
        super().__init__(locals())
        if direction is None:
            self.direction = direction
        else:
            self.direction = settings.validate_horizontal_arrows(direction)

    def main(self):
        if self.direction:
            press(self.direction, 1, down_time=0.1, up_time=0.05)
        else:
            if config.player_pos[0] > 0.5:
                press('left', 1, down_time=0.1, up_time=0.05)
            else:
                press('right', 1, down_time=0.1, up_time=0.05)
        press(Key.BLADE_TORNADO, 2)


class Sudden_Raid(Command):

    def main(self):
        press(Key.SUDDEN_RAID, 2)


class ErdaFountain(Command):

    def main(self):
        key_down("down")
        press(Key.ERDA_FOUNTAIN, 4)
        key_up("down")

class ErdaShower(Command):

    def main(self):
        press(Key.ERDA_FOUNTAIN, 2)

class Theater6_Point1_JUMP(Command):

    def main(self):
        key_down("right")
        press(Key.JUMP, n = 1, down_time = 0.109, up_time = 0.109)
        key_up("right")
        press(Key.JUMP, n = 1, down_time = 0.109, up_time = 0.203)
        press(Key.BOD, n = 2, down_time = 0.47, up_time = 0.01)


class Theater6_Point2_JUMP(Command):
    def main(self):
        key_down("left")
        time.sleep(0.073)
        press(Key.JUMP, n =1 , down_time = 0.094, up_time = 0.359)
        press(Key.JUMP, n =1, down_time = 0.125, up_time = 0.16)
        key_up("left")
        time.sleep(0.134)
        press(Key.BLADE_FURY, n = 1, down_time = 0.11, up_time = 0.328)

class Theater6_Point3_JUMP(Command):
    def main(self):
        key_down("left")
        time.sleep(0.172)
        press(Key.JUMP, n=1, down_time=0.093, up_time=0.297)
        press(Key.JUMP, n=1, down_time=0.125, up_time=0.141)
        press(Key.BLADE_TORNADO, n=1, down_time=0.109, up_time=0.250)
        key_up("left")

class TripleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)

class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)


class Final_Cut(Command):
    def main(self):
        press(Key.FINAL_CUT, n=1, down_time = 0.05, up_time = 0.01)

class CA4_Starting(Command):
    def main(self):
        key_down("right")
        time.sleep(0.156)
        press(Key.JUMP,n = 1, down_time = 0.125, up_time = 0.078)
        press(Key.JUMP, n=1, down_time=0.079, up_time=0.155)
        key_up("right")
        press(Key.BOD, n = 1, down_time = 0.078, up_time = 0.828)
        time.sleep(0.5)

        key_down("right")
        time.sleep(0.154)
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
        key_up("right")
        press(Key.PHANTOM_BLOW, n = 1, down_time=0.109, up_time=0.406)

        key_down("right")
        time.sleep(0.154)
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n=1, down_time=0.141, up_time=0.11)
        key_up("right")
        press(Key.PHANTOM_BLOW, n = 1,down_time=0.109, up_time=0.406)

        # key_down("right")
        # time.sleep(0.154)
        # press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        # #press(Key.JUMP, n=1, down_time=0.141, up_time=0.11)
        # key_up("right")
        # press(Key.PHANTOM_BLOW, n = 1,down_time=0.109, up_time=0.406)

class CA4_Door(Command):
    def main(self):
        time.sleep(0.05)
        key_down("right")
        press("up", n=7, down_time = 0.02, up_time = 0.02)
        key_up("right")
        time.sleep(0.05)


class CA4_Erda(Command):
    def main(self):
        press(Key.ERDA_FOUNTAIN, n = 1, down_time = 0.1, up_time = 1)
        time.sleep(0.18)
        key_down("down")
        time.sleep(0.078)
        press(Key.JUMP, n = 1, down_time = 0.156, up_time = 0.063)
        key_up("down")
        time.sleep(0.156)
        press(Key.DOUBLE_JUMP, n = 1, down_time = 0.01, up_time = 0.01)
        press(Key.BOD, n = 1, down_time = 0.094, up_time = 1.2)

        key_down("left")
        time.sleep(0.094)
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n=1, down_time=0.141, up_time=0.11)
        key_up("left")
        press(Key.PHANTOM_BLOW, n = 1,down_time=0.109, up_time=0.406)

class CA4_Tornado(Command):
    def main(self):
        time.sleep(0.5)
        press(Key.ROPE, n = 1, down_time = 0.094, up_time = 0.630)
        press(Key.ROPE, n = 1, down_time=0.078, up_time=0.266)
        key_down("left")
        press(Key.DOUBLE_JUMP, n=1, down_time=0.01, up_time=0.01)
        press(Key.BLADE_TORNADO, n =1, down_time = 0.01, up_time = 0.3)
        time.sleep(0.5)
        key_up("left")

