"""A collection of all commands that a Hero can use to interact with the game."""

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
    UP_ARROW = 'up'
    DOWN_ARROR = 'down'
    JUMP = 'space'
    UPWAIRD_CHARGE  = "s"  #up jump skill
    ROPE = 'alt'

    RUSH = 'd'
    SURGING_BLADE = "w"
    
    # Skills[Buffs]
    GREEN_POT = "="
    YELLO_POT = "-"

    # Skills[Damage:attack]
    PHANTOM_BLADE = "c"
    RAGING_BLOW = "a"
    
    
    FALCON_HONOR = "ctrl"
    INSTANCE_SLICE = "r"

    
    
    # Skills [Placement]
    ERDA_FOUNTAIN = "end"
    JIANSHEN = "1"
    SENGOKU ="3"

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
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction)
        time.sleep(0.05)
        press(Key.RAGING_BLOW,n = 1, down_time = 0.094, up_time = 0.046)
        time.sleep(0.335)

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
        self.direction = settings.validate_arrows(direction)
    def main(self):
        press(self.direction)
        press(Key.JUMP)
        time.sleep(0.1)
        press(Key.BEAM_BLADE,n = 3, down_time = 0.094, up_time = 0.046)
        time.sleep(0.275)

class AngleBeamBlade(Command):
    def __init__(self,hori_direction,veti_direction):
        super().__init__(locals())
        self.hori_direction = settings.validate_arrows(hori_direction)
        self.veti_direction = settings.validate_arrows(veti_direction)
    def main(self):
        key_down(self.hori_direction)
        key_down(self.veti_direction)
        
        press(Key.BEAM_BLADE,n = 3, down_time = 0.094, up_time = 0.046)
        key_up(self.hori_direction)
        key_up(self.veti_direction)
        time.sleep(0.275)






class JumpRagingBlow (Command):
    def __init__(self, direction,repetitions=1):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.repetitions = int(repetitions)
    def main(self):
        for _ in range(self.repetitions):
            press(self.direction,n=1,down_time=0.07)
            press(Key.JUMP, n = 2, down_time = 0.072, up_time = 0.01)
            
            press(Key.RAGING_BLOW,n = 1, down_time = 0.094, up_time = 0.046)
            time.sleep(0.375)
            

class JianShen(Command):
    def __init__(self):
        super().__init__(locals())
    def main(self):
        press(Key.JIANSHEN,4)




class ErdaFountain(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    def main(self):
        press(self.direction,2)
        press(Key.ERDA_FOUNTAIN,2)



class Buff(Command):

    def __init__(self):
        super().__init__(locals())
        
        
        
        self.buff_time_120 = 0
        '''
        self.monster_park_pot_30mins = 0
        self.buff_time_180 = 0
        '''

    def main(self):
        buffs_120 = [Key.SENGOKU,Key.JIANSHEN]
        now = time.time()
        '''
        buffs_1800 = [Key.GREEN_POT, Key.YELLO_POT]
        buffs_180 = [Key.DICE, Key.SHAPR_EYE, Key.COMBAT_ORDER]
        '''
        
        '''
        if self.monster_park_pot_30mins == 0 or now - self.monster_park_pot_30mins > 1800:
            for key in buffs_1800:
                press(key,1,down_time=0.5,up_time=0.3)
            self.monster_park_pot_30mins = now
        '''
        if self.buff_time_120 == 0 or now - self.buff_time_120 > 120:            
            for key in buffs_120:
                press(key, 3, up_time=0.3)
            self.buff_time_120 = now
        '''
        if self.buff_time_180 == 0 or now - self.buff_time_180 > 180:            
            for key in buffs_180:
                press(key, 3, up_time=0.4)
            self.buff_time_180 = now
            time.sleep(1)
        '''

class UpJump(Command):
    def main(self):
        press(Key.UPWAIRD_CHARGE)



class Rope(Command):
    def main(self):
        press(Key.ROPE, 1, up_time = 0.3)

class ShortRope(Command):
    def main(self):
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)
        press(Key.ROPE, 1,down_time=0.1, up_time = 0.1)

class will(Command):
    def main(self):
        press(Key.WILL, 1, up_time = 0.3)


class Move_right(Command):
    
    def __init__(self,key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)
    def main(self):
        press(Key.RIGHT_ARROW,n=1,down_time=self.key_down_time,up_time=0.01)

class Move_left(Command):
    
    def __init__(self,key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)
    def main(self):
        press(Key.LEFT_ARROW,n=1,down_time=self.key_down_time,up_time=0.01)



class DoubleJump(Command):
    def main(self):
        press(Key.JUMP, n = 1, down_time = 0.072, up_time = 0.01)
        press(Key.JUMP, n = 1, down_time=0.064, up_time=0.01)

class HighDoubleJump(Command):
    def __init__(self, direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        
    def main(self):
        press(self.direction)
        press(Key.JUMP, n = 1, down_time = 0.320, up_time = 0.0)
        press(Key.JUMP, n = 1, down_time=0.95, up_time=0.0)

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



class FalconHonor(Command):
    def main(self):
        press(Key.FALCON_HONOR,2)

class PhantomBlade(Command):
    def main(self):
        press(Key.PHANTOM_BLADE,2)



class SurgingBlade (Command):
    def __init__(self, direction,repetitions=1):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
        self.repetitions = int(repetitions)
    def main(self):
        for _ in range(self.repetitions):
            press(self.direction)
            press(Key.SURGING_BLADE,n = 1, down_time = 0.054, up_time = 0.016)


class InstanceSlice(Command):
    def main(self):
        
        press(Key.INSTANCE_SLICE,n= 2,down_time = 0.150, up_time = 0.0)

        
class Rush(Command):
    def __init__(self,direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    
    def main(self):
        press(self.direction)
        press(Key.RUSH,2)

class RushSurge(Command):
    def __init__(self,direction):
        super().__init__(locals())
        self.direction = settings.validate_horizontal_arrows(direction)
    
    def main(self):
        press(self.direction)
        press(Key.RUSH,1)
        press(Key.SURGING_BLADE,1)


class Move_Up(Command):
    
    def __init__(self,key_down_time=1):
        super().__init__(locals())
        self.key_down_time = float(key_down_time)
    def main(self):
        press(Key.UP_ARROW,n=1,down_time=self.key_down_time,up_time=0.01)




        