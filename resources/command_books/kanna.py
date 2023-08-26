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
    TELEPORT = '4'
    CHARM = 'z'

    # Buffs
    HAKU = 'f'
    AKATSUKI_WARRIOR = 'f5'
    HOLY_SYMBOL = 'f2'
    SPEED_INFUSION = 'f1'

    # Skills
    ERDA_FOUNTAIN = "home"

    SHIKIGAMI = '1'
    TENGU = '3'
    LUCID_SOUL = '6'
    YAKSHA = 'g'
    VANQUISHER = 'a'
    KISHIN = 'c'
    TOTEM = 'f4'
    NINE_TAILS = 'q'
    ARACHNID = '5'
    EXORCIST = '2'
    DOMAIN = 's'
    ONI_LEGION = '5'
    BLOSSOM_BARRIER = 'g'
    YUKIMUSUME = 'end'
    MANA_BALANCE = 'd'
    ROPE = "n"

#########################
#       Commands        #
#########################
def step(direction, error):
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
                    current_pos = config.player_pos
                    if d_x < 0:
                        key = 'left'
                    else:
                        key = 'right'
                    self._new_direction(key)
                    if abs(d_x) > settings.move_tolerance * 1.5:
                        press(Key.TELEPORT, 1)
                    if settings.record_layout:
                        config.layout.add(*config.player_pos)
                    counter -= 1
                    if i < len(path) - 1:
                        time.sleep(0.15)
                d_y = point[1] - config.player_pos[1]
                key_up(self.prev_direction)
                if abs(d_y) > settings.move_tolerance / math.sqrt(2):
                    if d_y < 0:  # targe is above player
                        if abs(d_y) < 0.5:
                            Teleport("up").main()
                        else:
                            Rope().main()
                            time.sleep(2)
                    else:  # targe is blow the player
                        if abs(d_y) < 0.15:
                            Teleport("down").main()
                        else:
                            key_down('down')
                            press(Key.JUMP, 2, 0.1, 0.01)
                            time.sleep(1)
                            key_up("down")
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
                        Teleport('up').main()
                        time.sleep(0.5)
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
        now = time.time()
        if self.haku_time == 0 or now - self.haku_time > 490:
            press(Key.HAKU, 2)
            press(Key.AKATSUKI_WARRIOR, 2)
            self.haku_time = now
        if self.buff_time == 0 or now - self.buff_time > 180:
            press(Key.NINE_TAILS, 3, 0.05, 0.05)
            self.buff_time = now


class Teleport(Command):
    """
    Teleports in a given direction, jumping if specified. Adds the player's position
    to the current Layout if necessary.
    """

    def __init__(self, direction, jump='False'):
        super().__init__(locals())
        self.direction = settings.validate_arrows(direction)
        self.jump = settings.validate_boolean(jump)

    def main(self):
        num_presses = 1
        time.sleep(0.05)
        if self.direction in ['up', 'down']:
            num_presses = 1
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
        press(Key.TELEPORT, num_presses)
        key_up(self.direction)
        if settings.record_layout:
            config.layout.add(*config.player_pos)


class Shikigami(Command):
    """Attacks using 'Shikigami Haunting' in a given direction."""

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
            press(Key.SHIKIGAMI, self.attacks, up_time=0.05)
        key_up(self.direction)
        if self.attacks > 2:
            time.sleep(0.3)
        else:
            time.sleep(0.2)





class Tengu(Command):
    """Uses 'Tengu Strike' once."""

    def main(self):
        press(Key.TENGU, 1, up_time=0.05)


class LucidSoul(Command):
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
        press(Key.LUCID_SOUL, 3)


class Yaksha(Command):
    """
    Places 'Ghost Yaksha Boss' in a given direction, or towards the center of the map if
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
        press(Key.YAKSHA, 8)


class Vanquisher(Command):
    """Holds down 'Vanquisher's Charm' until this command is called again."""

    def main(self):
        key_up(Key.VANQUISHER)
        time.sleep(0.075)
        key_down(Key.VANQUISHER)
        time.sleep(0.15)


class Kishin(Command):
    """Uses 'Kishin Shoukan' once."""

    def main(self):
        press(Key.KISHIN, 4, down_time=0.1, up_time=0.15)

class Rope(Command):
    """Uses 'Kishin Shoukan' once."""

    def main(self):
        press(Key.ROPE, 1, down_time=0.1, up_time=0.15)

class Totem(Command):

    def main(self):
        press(Key.TOTEM, 4, down_time=0.15, up_time=0.15 )

class NineTails(Command):
    """Uses 'Nine-Tailed Fury' once."""

    def main(self):
        press(Key.NINE_TAILS, 3)


class Arachnid(Command):
    """Uses 'True Arachnid Reflection' once."""

    def main(self):
        press(Key.ARACHNID, 3)


class Exorcist(Command):
    """Uses 'Exorcist's Charm' once."""

    def __init__(self, jump='False'):
        super().__init__(locals())
        self.jump = settings.validate_boolean(jump)

    def main(self):
        if self.jump:
            press(Key.JUMP, 1, down_time=0.1, up_time=0.15)
        press(Key.EXORCIST, 2, up_time=0.05)


class Domain(Command):
    """Uses 'Spirit's Domain' once."""

    def main(self):
        press(Key.DOMAIN, 3)


class Legion(Command):
    """Uses 'Ghost Yaksha: Great Oni Lord's Legion' once."""

    def main(self):
        press(Key.ONI_LEGION, 2, down_time=0.1)


class BlossomBarrier(Command):
    """Places a 'Blossom Barrier' on the ground once."""

    def main(self):
        press(Key.BLOSSOM_BARRIER, 2)


class Yukimusume(Command):
    """Uses 'Yuki-musume Shoukan' once."""

    def main(self):
        press(Key.YUKIMUSUME, 2)

class ErdaFountain(Command):

    def main(self):
        key_down("down")
        press(Key.ERDA_FOUNTAIN, 4)
        key_up("down")


class Balance(Command):
    """Restores mana using 'Mana Balance' once."""

    def main(self):
        press(Key.MANA_BALANCE, 2)


class Charm(Command):
    """Jumps up using 'Shikigami Charm'."""

    def main(self):
        press(Key.CHARM, 2)