# cool_grippers/

Curated gripper configs saved from past optimization runs. Each subfolder is one design worth keeping as a reference or starting point.

---

## Structure

```
cool_grippers/
├── gripper_0/
│   └── lab_config_0.jsonc
├── gripper_1/
│   └── lab_config_1.jsonc
└── gripper_N/
    └── lab_config_N.jsonc
```

Each `lab_config_X.jsonc` is a complete `ModelParams` parameter set in the same format as `config/lab_config.jsonc`.

---

## To use a saved gripper

Copy the config to the active slot:

```bash
cp cool_grippers/gripper_3/lab_config_3.jsonc config/lab_config.jsonc
```

Then generate the mesh:

```bash
python generation/generate_gripper.py
```

Or use the dashboard Generate tab after copying the file.

---

## To save a new design

Run the optimizer, find a trial you like in the leaderboard, copy its `runtime/trials/gen_XXXX/trial_XX/lab_config.jsonc` here as a new numbered folder, and rename the file to match the folder index.
Try and save an image to so you dont have to generate each time you want to see it
