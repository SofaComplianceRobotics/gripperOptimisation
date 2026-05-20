"""
Central timing configuration for all SOFA scenes.

Synchronizes dt (timestep) values across recording, inverse control, and direct simulation modes.
Change these values in one place to update all scenes.
"""

# Timestep for inverse control (trajectory recording, manual control)
# Larger step = smoother physics, easier manual control
DT_INVERSE = 0.05

# Timestep for direct simulation (optimization runs, playback)
# Smaller step = more accurate physics, more compute
DT_DIRECT = 0.02

# Safe timestep for the 2 contact-resolution frames right after cube spawn.
# Switched to DT_DIRECT once contacts are settled.
DT_CONTACT = 0.01
