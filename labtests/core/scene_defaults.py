"""Default physics and scoring values for the direct-mode (cube-pick) scenes.

Single source of truth: scenes read these through PlaybackConfig.from_env(),
which lets individual values be overridden per-process via the matching env
var (e.g. ``$env:CUBE_MASS_MAX = "2.5"``) for one-off experiments without
editing code. With no env vars set, scenes run standalone on these values.
"""

from geometry.timing_config import DT_DIRECT

# ─────────────────────────────────────────────
# Contact physics
# ─────────────────────────────────────────────
FRICTION_COEF = 0.6  # contact friction coefficient (mu)

# ─────────────────────────────────────────────
# Cube spawn / floor layout
# ─────────────────────────────────────────────
FLOOR_CENTER_Y = -230.0
CUBE_SPAWN_CLEARANCE = 10.0
CUBE_SPAWN_TIME = 0.4
CUBE_PRESPAWN_OFFSET = 200.0
DROP_BELOW_SPAWN_TOL = 0.5
PICKUP_ABOVE_SPAWN_TOL = 1.0

# ─────────────────────────────────────────────
# Cube mass and overload ramp
# ─────────────────────────────────────────────
CUBE_MASS_START = 0.005  # kg, initial cube mass
CUBE_MASS_MAX = 1.0  # kg reached by the end of the overload ramp
CUBE_MASS_RAMP_TIME = 8.0  # seconds to ramp from start mass to max mass
OVERLOAD_MAX_TIME = 5.0  # seconds of post-recording overload simulation

# ─────────────────────────────────────────────
# Pickup / drop thresholds
# ─────────────────────────────────────────────
FLOOR_Y_THRESHOLD = -235.0  # cube Y below this = on the floor / never picked up
FLOOR_Y_BUFFER = 5.0  # how far above threshold counts as "still on floor"
PICKUP_Y_THRESHOLD = -215.0  # cube Y above this = considered picked up

# ─────────────────────────────────────────────
# Scoring and early stop
# ─────────────────────────────────────────────
# Scaled so the gate fires after the same number of recorded frames
# regardless of DT_DIRECT.
EARLY_STOP_SIM_TIME = 2.0 * (DT_DIRECT / 0.02)
DROP_PENALTY = 50.0  # score if the cube is dropped after at least one pickup
EARLY_CONTACT_STOP_TIME = 0.6
EARLY_CONTACT_PENALTY = -1.0
NO_PICKUP_PENALTY = 0.0

# ─────────────────────────────────────────────
# Under-cube invalid-geometry check
# ─────────────────────────────────────────────
ENABLE_UNDERCUBE_CHECK = False  # if False, skip the under-cube malus rule
UNDERCUBE_PENALTY = -0.2
UNDERCUBE_MARGIN = 0.0