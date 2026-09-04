# labtests/grasp_hold/

The standard cube-grasp-and-lift benchmark, and the default-selected test.

Direct mode: replays a recorded motor trajectory, spawns an 8 mm cube, and
scores by **hold time** — seconds the cube stays above the pickup threshold
after the recording ends, accumulated only past the `early_stop_sim_time`
gate. An overload phase then ramps the cube mass up to `cube_mass_max` and
keeps scoring, so a stronger grip scores higher.

All the physics and scoring logic lives in `labtests/core`
(`PlaybackConfig`, `BasePlaybackController`). This folder only sets the
record-file path and the cube scale.

The per-trial recording comes from `sofaopt_project.py`'s `prepare_trial`
hook (this trial's own gripper + leg geometry, driven through the inverse
solver). A manual launch falls back to
`runtime/recordings/grasp_hold/motor_recording.json`.
