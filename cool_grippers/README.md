# cool_grippers/

Curated gripper designs saved from past optimization runs. Each `gripper_*/`
folder is one design worth keeping as a reference or a starting point.

---

## Layout

```
cool_grippers/
├── gripper_0/
│   └── lab_config.jsonc      ← the parameter set
├── gripper_2/
│   ├── lab_config.jsonc
│   └── preview.png           ← render of the gripper (optional)
├── gripper_8/
│   ├── lab_config.jsonc
│   ├── gripper.stl           ← exported meshes (optional)
│   └── leg.stl
└── gripper_baseline/
    ├── lab_config.jsonc
    ├── preview.png
    ├── gripper.stl
    └── leg.stl
```

Every `lab_config.jsonc` is a complete parameter set in the same format as
`config/lab_config.jsonc`. The older designs (`gripper_0`–`gripper_7`) carry
only the shape parameters; the newer ones also include the `leg_*` keys.

---

## Use a saved design

Copy its config into the active slot, then generate:

```bash
cp cool_grippers/gripper_3/lab_config.jsonc config/lab_config.jsonc
python generation/generate_gripper.py
```

Or pick it up from the dashboard Generate tab after copying the file.

---

## Save a new design

1. Run the optimizer and find a trial you like in the leaderboard.
2. Make a new `cool_grippers/gripper_N/` folder.
3. Copy `runtime/trials/gen_XXXX/trial_XX/params.json` into it as
   `lab_config.jsonc` (same JSON, the `.jsonc` name just allows comments).
4. Optionally add a `preview.png` so you don't have to regenerate it to see
   the shape, and `gripper.stl` / `leg.stl` if you want the meshes on hand.
