"""A collection of all commands that a Kanna can use to interact with the game."""
import random

from src.easymaple.common import config, settings, utils
import time
import math
from src.easymaple.routine.components import Command
from src.easymaple.common.vkeys import press, key_down, key_up
import numpy as np


# List of key mappings
class Key:
    # Movement
    JUMP = 'space'

    # Skills
    SHOW_DOWN = "1"
    QUAD_STAR = "2"
    DARK_FLARE = "g"
    LEAP = "z"
    SUDDEN_RAID = "w"
    DEATH_STAR = "a"
    WARRIOR = "f5"
    OMEN = "r"
    DASH="4"
    SHURI="t"
    BALL="page up"

    ERDA_FOUNTAIN = "c"
    ROPE  = "s"
    BUFF = "shift"


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
                    if abs(d_x) >= settings.move_tolerance * 20:
                        TripleJump().main()
                        counter -= 10
                    elif settings.move_tolerance * 10 <= abs(d_x) < settings.move_tolerance * 20:
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

    def __init__(self, x, y, max_steps=10):
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
                        time.sleep(0.025)
                        walk_counter += 1
                        d_x = self.target[0] - config.player_pos[0]
                    key_up('left')
                else:
                    key_down('right')
                    while config.enabled and d_x > 1.5 * threshold and walk_counter < 60:
                        time.sleep(0.025)
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
    """Presses each configured buff key once its cooldown elapses.

    BUFFS maps a key (entry from `Key`) to its cooldown in seconds. Each
    press is followed by `dismiss_buff_active_popup()` so any "buff still
    active" / "same potion in effect" dialog is cleared before the routine
    resumes.
    """

    BUFF_BUFFER = 10

    BUFFS = {
        "f1": 30 * 60,
        "f5": 120 * 60
    }

    def __init__(self):
        super().__init__(locals())
        self.last_pressed = {key: 0.0 for key in self.BUFFS}

    def main(self):
        now = time.time()
        for key, cooldown in self.BUFFS.items():
            last = self.last_pressed.get(key, 0.0)
            if last == 0.0 or now - last > cooldown + self.BUFF_BUFFER:
                press(key, 1, 0.1, 2)
                self.dismiss_buff_active_popup()
                time.sleep(1)
                self.last_pressed[key] = now


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


class CB1_POINT_1(Command):
    def __init__(self):
        super().__init__(locals())
        self.timer =0
    def main(self):
        while True:
            if self.timer == 0 or time.time() - self.timer > 59:
                self.timer = time.time()
                break
            press("right", 1, 0.094, 0.0123, random=True)
            press(Key.SHOW_DOWN, 1, 0.120, 0.24, random=True)
            time.sleep(np.random.uniform(0.5, 1))
            press("left", 1, 0.084, 0.0123, random=True)
            press(Key.SHOW_DOWN, 1, 0.120, 0.24, random=True)
            time.sleep(np.random.uniform(0.5, 1))

            press(Key.JUMP, 1, 0.1, 0.1)
            press("right", 1, 0.05)
            press(Key.SHOW_DOWN, 1, 0.120, 0.24, random=True)
            time.sleep(np.random.uniform(0.5, 1))
            press(Key.JUMP, 1, 0.1, 0.1)
            press("left", 1, 0.05)
            press(Key.SHOW_DOWN, 1, 0.120, 0.24, random=True)
            time.sleep(np.random.uniform(0.5, 1))






class CB1_POINT_11(Command):
    def __init__(self):
        super().__init__(locals())
    def main(self):
        press(Key.OMEN, 1, 0.1, 0.2, random=True)
        press("left", 1, 0.084, 0.0123)
        TripleJumpAttack("left").main()

        for _ in range(10):
            if abs(config.player_pos[1]  - 0.190) < 0.005:
                break
            time.sleep(0.05)


class CB1_POINT_2(Command):
    def main(self):
        key_down("down")
        time.sleep(0.1)
        press(Key.JUMP, 1, 0.120, 0.24)
        key_down("left")
        time.sleep(0.1)
        press(Key.DASH)
        time.sleep(0.1)
        key_up("down")
        key_up("left")
        for _ in range(30):
            if abs(config.player_pos[1] - 0.265) < 0.001:
                break
            time.sleep(0.1)



class CB1_POINT_3(Command):
    def main(self):
        press(Key.DARK_FLARE, 2, 0.1, 0.1, random=True)
        key_down("down")
        press(Key.JUMP, 2, 0.120, 0.094)
        key_up("down")
        for _ in range(30):
            if abs(config.player_pos[1] - 0.344) < 0.001:
                break
            time.sleep(0.1)
        time.sleep(0.2)


class CB1_POINT_4(Command):
    def main(self):
        for _ in range(3):
            TripleJumpAttack("right").main()
        for _ in range(30):
            if abs(config.player_pos[1] - 0.344) < 0.001:
                break
            time.sleep(0.05)
        time.sleep(0.1)


class CB1_POINT_5(Command):
    def main(self):
        key_down("left")
        time.sleep(0.4)
        press(Key.JUMP, 1, 0.120, 0.094)
        press(Key.LEAP, 1, 0.1, 0.2)
        key_up("left")
        press("right", 1, 0.1, 0.01)
        time.sleep(0.8)
        press("right", 1, 0.1, 0.01)
        press(Key.ERDA_FOUNTAIN, 1, 0.1, 0.65, random=True)
        press(Key.JUMP, 1, down_time = 0.140, up_time = 0.100)
        press(Key.LEAP, 1, down_time = 0.225, up_time = 0.5)
        time.sleep(0.1)

class CB1_POINT_6(Command):

    def main(self):
        press(Key.SUDDEN_RAID, 1, 0.1, 0.6)
        key_down("left")
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.096)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.36)
        key_up("left")
        press(Key.DASH, 1, 0.1, 0.1)
        time.sleep(0.2)
        time.sleep(0.5)
        press(Key.SHURI,1, 0.1, 0.4)


def small_jump(direction: str, delay=0.4):
    press(direction, 1, 0.01)
    press(Key.JUMP, 1, 0.1, delay)
    press(Key.JUMP, 1, 0.1, 0.2)

class BC4_ATTACK_POINT(Command):
    def __init__(self):
        super().__init__(locals())
        self.timer = 0
    def main(self):
        while True:
            if self.timer == 0 or time.time() - self.timer > 61:
                self.timer = time.time()
                break
            else:
                press(Key.SHOW_DOWN, 2, 0.2, 0.50)
                time.sleep(np.random.uniform(2, 2.5))
        press(Key.OMEN, 1, 0.1, 0.4)
        small_jump("left", 0.38)
        time.sleep(0.5)
        small_jump("left", 0.32)
        time.sleep(0.1)

class BC4_BALL_1(Command):
    def __init__(self):
        super().__init__(locals())
        self.timer = 0
    def main(self):
        if time.time() - self.timer < 60 or self.timer != 0:
            difference = 60 - (time.time() - self.timer)
            for _ in range(int(difference // 1) + 1):
                press(Key.SHOW_DOWN, 1, 0.1, 0.9)

        press(Key.BALL, 1, 0.2, 0.4)
        self.timer = time.time()
        press("right", 1, 0.20)
        small_jump("right", 0.32)
        time.sleep(0.5)


class BC4_DARK_FLARE(Command):
    def __init__(self):
        super().__init__(locals())
        self.timer = 0
    def main(self):
        if time.time() - self.timer < 58 or self.timer != 0:
            difference = 58 - (time.time() - self.timer)
            for _ in range(int(difference // 1) + 1):
                press(Key.SHOW_DOWN, 1, 0.1, 0.9)

        press(Key.DARK_FLARE, 1, 0.1, 0.7)
        self.timer = time.time()
        small_jump("right", 0.3)
        time.sleep(0.5)

class BC4_BALL_2(Command):
    def __init__(self):
        super().__init__(locals())
        self.timer = 0
    def main(self):
        press(Key.BALL, 1, 0.2, 0.4)
        self.timer = time.time()
        press("right", 1, 0.15)
        small_jump("right", 0.35)
        time.sleep(0.5)

class BC4_ERDA(Command):
    def __init__(self):
        super().__init__(locals())
        self.timer = 0
    def main(self):
        if time.time() - self.timer < 58 or self.timer != 0:
            difference = 58 - (time.time() - self.timer)
            for _ in range(int(difference // 1) + 1):
                press(Key.SHOW_DOWN, 1, 0.1, 0.9)

        press(Key.SUDDEN_RAID, 1, 0.1, 0.7)
        press(Key.ERDA_FOUNTAIN, 1, 0.1, 0.7)
        self.timer = time.time()
        press("right", 1, 0.45)
        small_jump("right")
        time.sleep(0.5)

class BC4_BALL_3(Command):
    def __init__(self):
        super().__init__(locals())
        self.timer = 0
    def main(self):

        press(Key.DEATH_STAR,1,0.1,0.7)
        press(Key.BALL, 1, 0.2, 0.4)
        self.timer = time.time()
        press("left", 1, 0.2)
        small_jump("left", 0.3)
        time.sleep(0.5)
        press("left", 1, 0.2)
        small_jump("left", 0.3)
        time.sleep(0.5)
        press("left", 1, 0.5)
        press(Key.SHURI, 1, 0.1, 0.7)


class FFP3_STAND_STILL(Command):
    def __init__(self):
        super().__init__(locals())
        self.show_down_time = 0
        self.death_star_time = 0
        self.ball_time = 0
        self.placed = False
        self.placed_time = 0

    def main(self):
        for _ in range(500):
            if config.enabled is False:
                time.sleep(0.5)
                break

            if self.ball_time == 0 or time.time() - self.ball_time > 115 and time.time() - self.placed_time > 57:
                self.ball_time = time.time()
                self.placed = False
                break

            if time.time() - self.ball_time > 57 and self.placed is False:
                self.placed = True
                self.placed_time = time.time()
                press(Key.DARK_FLARE, 2, 0.1, 0.2)
                press(Key.ERDA_FOUNTAIN, 2, 0.1, 0.2)

            press("left", 1,0.05, 0.01)
            press(Key.SHOW_DOWN, 1, 0.2, 1)
            press("right", 1, 0.05, 0.01)
            press(Key.SHOW_DOWN, 1, 0.2, 1)
            Adjust(0.524, 0.321).main()
            time.sleep(np.random.uniform(1, 1.5))


class FFP3_START_MOVE(Command):
    def main(self):
        press(Key.DARK_FLARE, 2, 0.1, 0.2)
        press(Key.ERDA_FOUNTAIN, 2, 0.1, 0.2)
        press(Key.OMEN, 2, 0.1, 0.3)
        DoubleJumpAttack("left").main()


class FFP3_LFET_BOT_PORTAL(Command):
    _target_point_1 = (0.305, 0.326)
    _target_point_2 = (0.380, 0.171)
    def main(self):
        for _ in range(100):
            if utils.distance(self._target_point_1, config.player_pos) < 0.03:
                press("up", 1, 0.05, 0.01)
            if utils.distance(self._target_point_2, config.player_pos) < 0.1:
                break
            if utils.distance(self._target_point_1, config.player_pos) < 0.002:
                continue
            x_distance = config.player_pos[0] - self._target_point_1[0]
            direction = "right" if x_distance < 0 else "left"
            press(direction, 1, abs(self._calculate_move_time(direction, x_distance)))

    def _calculate_move_time(self, direction: str, distance) -> float:
        base_value = max(distance * 6, 0.03)
        return base_value if direction == "left" else 1.8 * base_value


class FFP3_LFET_TOP_PORTAL(Command):
    _target_point = (0.759, 0.321)

    def main(self):
        press(Key.BALL, 2, 0.1, 0.2)
        for _ in range(10):
            press("up", 1 ,0.05, 0.01)

            if utils.distance(self._target_point, config.player_pos) < 0.03:
                break


class FFP3_RIGHT_BOT_PORTAL(Command):
    _target_point = (0.305, 0.326)
    def main(self):
        press(Key.BALL, 2, 0.1, 0.2)
        time.sleep(1)
        for _ in range(10):
            press("up", 1, 0.05, 0.01)

            if utils.distance(self._target_point, config.player_pos) < 0.03:
                break


class FFP3_BOT_LEFT_BALL(Command):
    def main(self):
        press(Key.BALL, 2, 0.1, 0.2)
        time.sleep(1)
        DoubleJumpAttack("right").main()


class NIGHT_ROAD_1_MID_STANDSTILL(Command):
    SELF_POSITION = (0.476, 0.256)
    NEXT_POSITION_RIGHT = (0.770, 0.262)
    NEXT_POSITION_LEFT = (0.182, 0.267)
    def __init__(self):
        super().__init__(locals())
        self.show_down_time = 0
        self.death_star_time = 0
        self.ball_time = 0
        self.placed = False
        self.placed_time = 0

    def get_into_portal(self, this_port_position, next_portal_position):
        for _ in range(100):
            if utils.distance(this_port_position, config.player_pos) < 0.03:
                press("up", 1, 0.05, 0.01)
            if utils.distance(next_portal_position, config.player_pos) < 0.1:
                break
            if utils.distance(this_port_position, config.player_pos) < 0.002:
                continue
            x_distance = config.player_pos[0] - this_port_position[0]
            direction = "right" if x_distance < 0 else "left"
            press(direction, 1, abs(self._calculate_move_time(direction, x_distance)))

    def place(self):
        self.get_into_portal(self.SELF_POSITION, self.NEXT_POSITION_RIGHT)
        press(Key.DARK_FLARE, 1, 0.1, 0.8)
        self.get_into_portal(self.NEXT_POSITION_RIGHT, self.NEXT_POSITION_LEFT)
        press(Key.ERDA_FOUNTAIN, 1, 0.1, 0.8)
        self.get_into_portal(self.NEXT_POSITION_LEFT, self.SELF_POSITION)



    def _calculate_move_time(self, direction: str, distance) -> float:
        base_value = max(distance * 6, 0.03)
        return base_value if direction == "left" else 1.8 * base_value

    def main(self):
        for _ in range(500):
            if config.enabled is False:
                time.sleep(0.5)
                break

            # Yield to the rune solver if a rune appeared during this point.
            # The bot's main loop will solve the rune before stepping to the
            # next routine point, then resume the routine.
            if config.bot.rune_active:
                break

            if self.ball_time == 0 or time.time() - self.ball_time > 117 and time.time() - self.placed_time > 59:
                self.ball_time = time.time()
                self.placed = False
                break

            if time.time() - self.ball_time > 59 and self.placed is False:
                self.placed = True
                self.placed_time = time.time()
                self.place()
            
            seed = random.randint(0, 1)

            if seed < 0.25:
                press(Key.SHOW_DOWN, 1, 0.1, 1)
            elif 0.25 < seed < 0.75:
                press(Key.JUMP, 1, 0.05, 0.05)
                press(random.choice(["left", "right"]), 1, 0.01, 0.01)
                press(Key.SHOW_DOWN, 1, 0.1, 0.01)
            else:
                press(Key.QUAD_STAR, 1, 0.1, 0.3)

            time.sleep(np.random.uniform(1, 1.5))
            Adjust(self.SELF_POSITION[0], self.SELF_POSITION[1]).main()
            time.sleep(np.random.uniform(0.5, 0.8))


class NIGHT_ROAD_1_MID_MOVE(Command):
    SELF_POSITION = (0.476, 0.256)
    NEXT_POSITION = (0.770, 0.262)
    def main(self):
        press(Key.OMEN, 2, 0.1, 0.3)
        for _ in range(100):
            if utils.distance(self.SELF_POSITION, config.player_pos) < 0.03:
                press("up", 1, 0.05, 0.01)
            if utils.distance(self.NEXT_POSITION, config.player_pos) < 0.1:
                break
            if utils.distance(self.SELF_POSITION, config.player_pos) < 0.002:
                continue
            x_distance = config.player_pos[0] - self.SELF_POSITION[0]
            direction = "right" if x_distance < 0 else "left"
            press(direction, 1, abs(self._calculate_move_time(direction, x_distance)))

    def _calculate_move_time(self, direction: str, distance) -> float:
        base_value = max(distance * 6, 0.03)
        return base_value if direction == "left" else 1.8 * base_value


class NIGHT_ROAD_1_RIGHT(Command):
    SELF_POSITION = (0.770, 0.262)
    NEXT_POSITION = (0.182, 0.267)
    def main(self):
        press(Key.BALL, 2, 0.1, 0.3)
        press(Key.DARK_FLARE, 1, 0.1, 0.5)
        for _ in range(100):
            if utils.distance(self.SELF_POSITION, config.player_pos) < 0.03:
                press("up", 1, 0.05, 0.01)
            if utils.distance(self.NEXT_POSITION, config.player_pos) < 0.1:
                break
            if utils.distance(self.SELF_POSITION, config.player_pos) < 0.002:
                continue
            x_distance = config.player_pos[0] - self.SELF_POSITION[0]
            direction = "right" if x_distance < 0 else "left"
            press(direction, 1, abs(self._calculate_move_time(direction, x_distance)))

    def _calculate_move_time(self, direction: str, distance) -> float:
        base_value = max(distance * 6, 0.03)
        return base_value if direction == "left" else 1.8 * base_value


class NIGHT_ROAD_1_LEFT(Command):
    SELF_POSITION = (0.182, 0.267)
    NEXT_POSITION = (0.476, 0.256)

    def main(self):
        press(Key.ERDA_FOUNTAIN, 1, 0.1, 0.7)
        press(Key.BALL, 2, 0.1, 0.2)
        for _ in range(100):
            if utils.distance(self.SELF_POSITION, config.player_pos) < 0.03:
                press("up", 1, 0.05, 0.01)
            if utils.distance(self.NEXT_POSITION, config.player_pos) < 0.1:
                break
            if utils.distance(self.SELF_POSITION, config.player_pos) < 0.002:
                continue
            x_distance = config.player_pos[0] - self.SELF_POSITION[0]
            direction = "right" if x_distance < 0 else "left"
            press(direction, 1, abs(self._calculate_move_time(direction, x_distance)))

        press(Key.BALL, 2, 0.1, 0.2)

    def _calculate_move_time(self, direction: str, distance) -> float:
        base_value = max(distance * 6, 0.03)
        return base_value if direction == "left" else 1.8 * base_value