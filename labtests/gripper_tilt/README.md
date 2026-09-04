# labtests/gripper_tilt/

Inverse-mode tilt test. Not selected by default.

`scene.py` moves the effector through a short list of `WAYPOINTS` and, at
each one, measures the Y-spread of the four effector points (a proxy for how
level the gripper stays). The score is `40 - sum(worst spread per waypoint)`,
so a gripper that holds its pose flat through the sequence scores near
`MAX_SCORE` (40).

All the scene infrastructure comes from `labtests/core`; this folder only
owns the waypoint list and the `TiltController` that walks it.
