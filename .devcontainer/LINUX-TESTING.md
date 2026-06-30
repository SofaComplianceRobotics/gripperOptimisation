# Testing lab_shapeOPT on Linux for free (GitHub Codespaces)

You don't need a Linux machine or admin rights on your laptop. A Codespace is a
cloud Ubuntu VM you control as root, reached from a browser. Free tier: ~60h/month.

## 1. Get the repo on GitHub
Push this repo (private is fine):
```bash
git push -u origin experimental/portable-bundle
```

## 2. Create the Codespace
On the GitHub repo page: **Code -> Codespaces -> Create codespace on
`experimental/portable-bundle`**. It builds from `.devcontainer/` automatically:
Python 3.10, a browser desktop, and all the X11/OpenGL/Qt libs SOFA's GUI needs.

## 3. Open the desktop
When the build finishes, the **Ports** tab shows `6080 (Desktop / noVNC)`. Open it
in a browser tab. Password: `vscode`. This is your Linux desktop where the
EmioLabs / SOFA windows appear.

## 4. Install EmioLabs (Linux AppImage)
In the Codespace terminal, download the EmioLabs Linux AppImage, then unpack it
**without FUSE** (containers usually can't mount FUSE):
```bash
chmod +x EmioLabs*.AppImage
./EmioLabs*.AppImage --appimage-extract     # extracts to ./squashfs-root/
./squashfs-root/AppRun                       # launch (window shows in the noVNC tab)
```

## 5. Add this lab to EmioLabs
Build the Linux bundle of the lab and unzip it into the EmioLabs assets folder
(adjust the destination to wherever EmioLabs installed):
```bash
tools/build_bundle.sh --source-only          # code-only zip (deps already shipped)
# or a full bundle if you have the SOFA root:
# tools/build_bundle.sh /path/to/emio-labs/resources/sofa

unzip dist/lab_shapeOPT_*_linux.zip -d ~/.local/share/emio-labs/.../assets/labs/
```
Then relaunch EmioLabs and open the lab from its optimisation panel.

## Headless shortcuts (no desktop needed)
- Run the optimizer: `python optimization/orchestrator.py`
- Run the dashboard: `python launcher/launch_web.py` -> open forwarded port **8050**
- Run the tests: `python -m pytest`

## Notes / gotchas
- **3D is software-rendered** (`LIBGL_ALWAYS_SOFTWARE=1`). The SOFA viewport opens
  but is slow — fine for "does it load and run," not for smooth interaction.
- If the EmioLabs window fails with a Qt `xcb` plugin error, a needed library is
  missing — add it to `.devcontainer/setup.sh` and rebuild the container.
- AppImages that demand FUSE at runtime: always use `--appimage-extract` + `AppRun`.
