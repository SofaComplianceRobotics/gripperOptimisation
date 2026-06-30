#!/usr/bin/env bash
# Codespace provisioning for running EmioLabs + lab_shapeOPT with a GUI.
#
# Installs the X11 / OpenGL / Qt shared libraries the SOFA (runSofa) viewer and
# the EmioLabs Qt window need, plus the tools to unpack an AppImage without FUSE.
# Then installs the lab's pure-Python deps so `pytest` and the dashboard run.
set -euo pipefail

echo "==> Installing system libraries (X11 / OpenGL / Qt / AppImage tooling) ..."
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  libglu1-mesa libgl1-mesa-dri libegl1 libopengl0 libglx-mesa0 \
  libxrender1 libxext6 libxi6 libxrandr2 libxfixes3 libxcursor1 \
  libxinerama1 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-cursor0 \
  libglib2.0-0 libdbus-1-3 libfontconfig1 libfreetype6 \
  fuse libfuse2 zsync file unzip

echo "==> Installing lab Python dependencies (requirements-bundle.txt) ..."
python -m pip install --upgrade pip
python -m pip install -r tools/requirements-bundle.txt

echo ""
echo "==> Done. Next steps:"
echo "    1. Open the forwarded port 6080 ('Desktop (noVNC)') -> password: vscode"
echo "    2. In a terminal, download the EmioLabs Linux AppImage, then:"
echo "         chmod +x EmioLabs*.AppImage"
echo "         ./EmioLabs*.AppImage --appimage-extract     # FUSE-free unpack"
echo "         ./squashfs-root/AppRun                       # launch the platform"
echo "    3. Drop this lab into the EmioLabs assets/labs/ folder (see LINUX-TESTING.md)."
