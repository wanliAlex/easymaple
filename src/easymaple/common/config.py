"""A collection of variables shared across multiple modules."""


#########################
#       Constants       #
#########################
RESOURCES_DIR = 'resources'


#################################
#       Global Variables        #
#################################
# The player's position relative to the minimap
player_pos = (0, 0)

# Describes whether the main bot loop is currently running or not
enabled = False

# If there is another player in the map, Auto Maple will purposely make random human-like mistakes
stage_fright = False

# Represents the current shortest path that the bot is taking
path = []


#############################
#       Shared Modules      #
#############################
# A Routine object that manages the 'machine code' of the current routine
routine = None

# Stores the Layout object associated with the current routine
layout = None

# Shares the main bot loop
bot = None

# Shares the video capture loop
capture = None

# Shares the keyboard listener
listener = None

# Shares the notifier (rune detection, Discord, audio alerts)
notifier = None

# Shares the gui to all modules
gui = None


# AdvancedSettings instance — populated by the GUI on init. Worker threads read
# detection thresholds from here. Stays None until GUI initializes it.
advanced = None

# LieDetectorSettings instance — populated by the GUI on init. The notifier
# reads the 'auto solve' / 'shadow' toggles from here; None (GUI not up yet) is
# treated as disabled (Discord handover instead of auto-solving).
lie_detector = None

# True while a Lie Detector game window is open (routine paused): the capture
# thread then skips its minimap/player work and grabs frames ~2x as often (the
# solver wants frames). Never while the routine runs - it needs player_pos.
capture_fast = False

# QWorldReentry instance (modules/qworld.py), created by the notifier. Watches
# for the Q-World timer kick and walks back through the lobby portal.
qworld = None

# The LieDetectorSession of the game being played right now (None otherwise).
# The listener's takeover hotkey signals it; the player polls it.
lie_detector_session = None

# Live match scores for the rune templates: (score, timestamp). Updated by the
# notifier (map score) and bot (buff score) loops; read by the Advanced UI for
# live preview. Stale (>2s) values display as "—".
last_rune_map_score = (0.0, 0.0)
last_rune_buff_score = (0.0, 0.0)
