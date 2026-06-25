"""Default physics and scoring values for the direct-mode (cube-pick) scenes.

Single source of truth: scenes read these through PlaybackConfig.from_env(),
which lets individual values be overridden per-process via the matching env
var (e.g. ``$env:CUBE_MASS_MAX = "2.5"``) for one-off experiments without
editing code. With no env vars set, scenes run standalone on these values.
"""

# ─────────────────────────────────────────────
# Contact physics
# ─────────────────────────────────────────────
# Contact friction coefficient (mu). A cube squeezed between finger faces
# tilted more than arctan(mu) from vertical squirts upward regardless of squeeze
# force. The collision mesh's grip faces sit ~28deg from vertical, so 0.6
# (~31deg threshold) wedges immediately. 1.5 (~56deg threshold) matches real
# silicone pads and also stands in for the conforming grip the rigid collision
# surface cannot reproduce.
FRICTION_COEF = 1.2

# ─────────────────────────────────────────────
# Motor playback
# ─────────────────────────────────────────────
# Trajectory replay speed. 1.0 plays the recording at its captured rate
# (motor positions interpolated between recorded frames at every physics
# step). Values > 1 compress the trajectory — faster runs, harsher dynamics.
PLAYBACK_TIME_SCALE = 1.0

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
# kg, initial cube mass. Kept above ~0.02 on purpose: at the old 0.005 (5 g) the
# cube is so light that the contact impulse needed to stop penetration flicks it
# out of the grip before the fingers can load up (it shoots upward even on a
# barely-closed grip, while the fingers visibly bend against the immovable
# floor). 0.03 kg sits in the stable-and-grippable window; the mass ramp
# (CUBE_MASS_MAX over CUBE_MASS_RAMP_TIME) still does the overload test from here.
CUBE_MASS_START = 0.02
CUBE_MASS_MAX = 1.0  # kg reached by the end of the overload ramp
CUBE_MASS_RAMP_TIME = 8.0  # seconds to ramp from start mass to max mass
OVERLOAD_MAX_TIME = 1.0  # seconds of post-recording overload simulation

# ─────────────────────────────────────────────
# Pickup / drop thresholds
# ─────────────────────────────────────────────
FLOOR_Y_THRESHOLD = -235.0  # cube Y below this = on the floor / never picked up
FLOOR_Y_BUFFER = 5.0  # how far above threshold counts as "still on floor"
PICKUP_Y_THRESHOLD = -215.0  # cube Y above this = considered picked up

# ─────────────────────────────────────────────
# Scoring and early stop
# ─────────────────────────────────────────────
# Pickup gate (sim seconds): the cube must be lifted above the pickup
# threshold before this time, or the run stops as a no-pickup failure.
# Covers the grab portion (~first quarter) of the 20.25 s grasp trajectory
# at PLAYBACK_TIME_SCALE = 1.0 — rescale both together.
EARLY_STOP_SIM_TIME = 1.5

# Wall-clock seconds between live status writes to trial_state.json.
# Final score/pruned writes always bypass this throttle.
STATUS_WRITE_INTERVAL = 0.25
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
