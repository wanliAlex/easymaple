"""A collection of all commands that Shadower can use to interact with the game. 	"""

from src.easymaple.common import config, settings, utils
import time
import math
from src.easymaple.routine.components import Command
from src.easymaple.common.vkeys import press, key_down, key_up


# List of key mappings
class Key:
    # Movement
    RIGHT_ARROW = 'right'
    LEFT_ARROW = 'left'
    DOWN_ARROW = 'down'
    UP_ARROW = 'up'
    JUMP = 'alt' 
    DOUBLE_JUMP = "alt"
    SHADOW_ASSAULT = '4' 
    ROPE = 'ctrl'
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
    CRUEL_STAB = '6' 
    MESO_EXPLOSION = 'd' 
    SUDDEN_RAID = '1'
    DARK_FLARE = 'r' 
    SHADOW_VEIL = '2' 
    ERDA_SHOWER = 'page up' 
    TRICKBLADE = 'f'
    DASH = "e"
    SLASH_SHADOW_FORMATION = 'a'
    SONIC_BLOW = '3'
    WILL = "g"
    SEREN = "t"
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

class will(Command):
    def main(self):
        press(Key.WILL, 1, up_time=0.3)

class seren(Command):
    def main(self):
        press(Key.SEREN, 1, up_time=0.3)

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
class DashShort(Command):
    def main(self):
        press(Key.DASH, 3, 0.15, 0.05)

class JumpShadowAssaultBot(Command):
    def main(self):
        press(Key.JUMP, n=1, down_time=0.125, up_time=0.1)
        press(Key.JUMP, n=1, down_time=0.3, up_time=0.09)
        key_down(Key.LEFT_ARROW)
        key_down(Key.DOWN_ARROW)
        press(Key.SHADOW_ASSAULT, n=1, down_time=0.094, up_time=0.046)
        key_up(Key.LEFT_ARROW)
        key_up(Key.DOWN_ARROW)
        time.sleep(0.275)

class JumpShadowAssaultUpRight(Command):
    def main(self):
        press(Key.JUMP, n=1, down_time=0.125, up_time=0.1)
        press(Key.JUMP, n=1, down_time=0.3, up_time=0.09)
        key_down(Key.RIGHT_ARROW)
        key_down(Key.UP_ARROW)
        press(Key.SHADOW_ASSAULT, n=1, down_time=0.094, up_time=0.046)
        key_up(Key.RIGHT_ARROW)
        key_up(Key.UP_ARROW)
        time.sleep(0.275)

class JumpShadowAssaultBotRight(Command):
    def main(self):
        press(Key.JUMP, n=1, down_time=0.125, up_time=0.1)
        press(Key.JUMP, n=1, down_time=0.3, up_time=0.09)
        key_down(Key.RIGHT_ARROW)
        key_down(Key.DOWN_ARROW)
        press(Key.SHADOW_ASSAULT, n=1, down_time=0.094, up_time=0.046)
        key_up(Key.RIGHT_ARROW)
        key_up(Key.DOWN_ARROW)
        time.sleep(0.275)

class Move_right(Command):

    def __init__(self, key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)

    def main(self):
        press(Key.RIGHT_ARROW, n=1, down_time=self.key_down_time, up_time=0.01)


class Move_left(Command):

    def __init__(self, key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)

    def main(self):
        press(Key.LEFT_ARROW, n=1, down_time=self.key_down_time, up_time=0.01)

class Dash(Command):
    def __init__(self, direction, jump: bool = False):
        super().__init__(locals())
        self.direction = str(direction)
        self.jump = bool(jump)

    def main(self):
        if self.jump:
            press(Key.JUMP, 1, 0.05, 0.1)
        key_down(self.direction)
        press(Key.DASH, 1, 0.1, 0.4)
        key_up(self.direction)

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
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
			
class SingleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        
class DownJump(Command):
    def main(self):
        key_down("down")
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        key_up("down")

class UpJump(Command):
    def main(self):
        key_down("up")
        press(Key.JUMP, n = 1, down_time = 0.094, up_time = 0.046)
        press(Key.JUMP, n = 1, down_time=0.141, up_time=0.11)
        key_up("up")

class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)
			
class ShadowAssault(Command):
    """
    ShadowAssault in a given direction, jumping if specified. Adds the player's position
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
                press(Key.JUMP, 2, down_time=0.1)
            else:
                press(Key.JUMP, 1)
        if self.direction == 'up':
            key_down(self.direction)
            time.sleep(0.05)
        press(Key.SHADOW_ASSAULT, num_presses)
        press(Key.MESO_EXPLOSION, num_presses)
        key_up(self.direction)
        if settings.record_layout:
	        config.layout.add(*config.player_pos)

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

class CruelStab(Command):
    """Attacks using 'CruelStab' in a given direction."""

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
            press(Key.CRUEL_STAB, self.attacks, up_time=0.05)
        key_up(self.direction)
        if self.attacks > 2:
            time.sleep(0.3)
        else:
            time.sleep(0.2)

class JumpCruelStab (Command):
    def __init__(self, direction,repetitions=1):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.repetitions = int(repetitions)
    def main(self):
        for _ in range(self.repetitions):
            press(self.direction)
            press(Key.JUMP, n = 2, down_time = 0.072, up_time = 0.01)
            
            press(Key.CRUEL_STAB,n = 1, down_time = 0.094, up_time = 0.046)
            time.sleep(0.3)

class JumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        key_down(self.direction)
        DoubleJump().main()
        CruelStabNoD().main()
        key_up(self.direction)
        MesoExplosion().main()
        time.sleep(0.45)

class StraightJumpAttack(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction)
        DoubleJump().main()
        CruelStabNoD().main()
        MesoExplosion().main()
        time.sleep(0.4)

class MesoExplosion(Command):
    """Uses 'MesoExplosion' once."""

    def main(self):
        press(Key.MESO_EXPLOSION, 1, up_time=0.05)
		
class CruelStabNoD(Command):
    """Uses 'CruelStab' once."""

    def main(self):
        press(Key.CRUEL_STAB, 1, up_time=0.05)	
        
class DarkFlare(Command):
    """
    Uses 'DarkFlare' in a given direction, or towards the center of the map if
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
        press(Key.DARK_FLARE, 3)

class ShadowVeil(Command):
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
        press(Key.SHADOW_VEIL, 3)        		

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


class SuddenRaid(Command):
    """Uses 'SuddenRaid' once."""

    def main(self):
        press(Key.SUDDEN_RAID, 3)


class Arachnid(Command):
    """Uses 'True Arachnid Reflection' once."""

    def main(self):
        press(Key.ARACHNID, 3)

class TrickBlade(Command):
    """
    Uses 'TrickBlade' in a given direction, or towards the center of the map if
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
        press(Key.TRICKBLADE, 3)

class SlashShadowFormation(Command):
    """Uses 'SlashShadowFormation' once."""

    def main(self):
        press(Key.SLASH_SHADOW_FORMATION, 3)
		
class SonicBlow(Command):
    """Uses 'SonicBlow' once."""

    def main(self):
        press(Key.SONIC_BLOW, 3)