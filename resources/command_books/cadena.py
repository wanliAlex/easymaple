"""A collection of all commands that Shadower can use to interact with the game. 	"""

from src.easymaple.common import config, settings, utils
import time
import math
from src.easymaple.routine.components import Command
from src.easymaple.common.vkeys import press, key_down, key_up


# List of key mappings
class Key:
    # Movement
    JUMP = 'space' 
    DOUBLE_JUMP = "0"
    SHADOW_ASSAULT = 'e' 
    ROPE = 'page down'
    # Buffs
    SHADOW_PARTNER = 'f4' 
    MAPLE_WARRIOR = 'f4' 
    EPIC_ADVENTURE = 'z'
    SPEED_INFUSION = 'f4'
    HOLY_SYMBOL = 'f4'
    SHARP_EYE = 'f4'
    COMBAT_ORDERS = 'f4'
    ADVANCED_BLESSING = 'f4'

    # Skills
    THRASH= 'q' 
    SCIMITAR= 'w' 
    CRUSH = 'g'
    MAELSTROM= 'end' 
    BRICK = 's' 
    DAGGER = 'd'
    ARACHNID = 'insert' 
    ERDA_SHOWER = 'n' 
    CANNON = '5'
    VOID_STRIKE= 'b'
    CLAW = 'r'

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

class TripleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)

class Portal(Command):
    def __init__(self, direction, duration):
        super().__init__(locals())
        self.direction = direction
        self.duration = float(duration)

    def main(self):
        key_down(self.direction)
        press("up", int(self.duration // 0.04) + 1, 0.02, 0.02)
        key_up(self.direction)

class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.145, up_time=0.07)
			
class UpJump(Command):
    def main(self):
        key_down("up")
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
        key_up("up")

class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)
			

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

class Thrash(Command):
    """Attacks using 'Thrash' in a given direction."""

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
            press(Key.THRASH, self.attacks, up_time=0.05)
        key_up(self.direction)
        if self.attacks > 2:
            time.sleep(0.3)
        else:
            time.sleep(0.2)

class JumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        ThrashRandomDirection().main()
        key_up(self.direction)
        
        time.sleep(0.5)
class TripleJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        TripleJump().main()
        ThrashRandomDirection().main()
        key_up(self.direction)
        
        time.sleep(0.6)


class StraightJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction)
        DoubleJump().main()
        ThrashRandomDirection().main()
        time.sleep(0.4)
		
class ThrashRandomDirection(Command):
    """Uses 'Thrash' once."""

    def main(self):
        press(Key.THRASH, 1, up_time=0.08)	
        
class Maelstrom(Command):
    """
    Uses 'Maelstrom' in a given direction, or towards the center of the map if
    no direction is specified.
    """
    def main(self):
        press(Key.MAELSTROM, 1, up_time=0.3)
        press(Key.MAELSTROM, 1, up_time=0.3)
        
class Crush(Command):
    """
    Uses 'ShadowVeil' in a given direction, or towards the center of the map if
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
        press(Key.CRUSH, 3)  

class Claw(Command):
    """
    Uses 'ShadowVeil' in a given direction, or towards the center of the map if
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
        press(Key.CLAW, 3)              		



class ErdaShower(Command):
    """
    Use ErdaShower in a given direction, Placing ErdaFountain if specified. Adds the player's position
    to the current Layout if necessary.
    """

    def __init__(self, direction, jump='False'):
        super().__init__(locals())
        self.direction = settings.validate_arrows(direction)
        self.jump = settings.validate_boolean(jump)

    def main(self):
        num_presses = 3
        time.sleep(0.05)
        if self.direction in ['up', 'down']:
            num_presses = 2
        if self.direction != 'up':
            key_down(self.direction)
            time.sleep(0.05)
        if self.jump:
            if self.direction == 'down':
                press(Key.JUMP, 3, down_time=0.1)
            else:
                press(Key.JUMP, 1)
        if self.direction == 'up':
            key_down(self.direction)
            time.sleep(0.05)
        press(Key.ERDA_SHOWER, num_presses)
        key_up(self.direction)
        if settings.record_layout:
	        config.layout.add(*config.player_pos)

class UpJumpBrick(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        key_down('up')
        press(Key.BRICK,3)
        key_up('up')
        key_up(self.direction)
        
        time.sleep(0.6)


class Brick(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        press(Key.BRICK,3)
        key_up(self.direction)
        
        time.sleep(0.5)


class Dagger(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        
        press(Key.JUMP, 1)
        time.sleep(0.05)
        press(Key.DAGGER, 3)
        
        
        time.sleep(0.1)


class Arachnid(Command):
    """Uses 'True Arachnid Reflection' once."""

    def main(self):
        press(Key.ARACHNID, 3)

class Scimitar(Command):
    """
    Uses 'Scimitar' in a given direction, or towards the center of the map if
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
        press(Key.SCIMITAR, 3)

class Cannon(Command):
    """Uses 'SlashShadowFormation' once."""

    def main(self):
        press(Key.CANNON, 3)
		

