#!/usr/bin/env bash
# build_bundle.sh - Produce a self-contained lab_shapeOPT Linux distribution.
#
# Linux counterpart of build_bundle.ps1. Stages the lab source plus its
# Python 3.10 dependencies (installed with the emio-labs SOFA python so the ABI
# and the gmsh shared library match), then zips it. A user unzips the result
# into emio-labs/.../assets/labs and runs it - no pip, no venv.
#
# Usage:
#   tools/build_bundle.sh [SOFA_ROOT]
#   tools/build_bundle.sh --source-only [SOFA_ROOT]
#
# SOFA_ROOT is the emio-labs resources/sofa folder (or set EMIOLABS_SOFA_ROOT).
# If omitted, a few common locations are tried. --source-only skips the
# dependencies and produces a small code-only patch zip.

set -euo pipefail

SOURCE_ONLY=0
SOFA_ROOT="${EMIOLABS_SOFA_ROOT:-}"
for arg in "$@"; do
  case "$arg" in
    --source-only) SOURCE_ONLY=1 ;;
    *) SOFA_ROOT="$arg" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REQUIREMENTS="$SCRIPT_DIR/requirements-bundle.txt"
OUT_DIR="$LAB_ROOT/dist"

find_sofa_python() {
  local root="$1" rel
  for rel in bin/python/bin/python3 bin/python/bin/python bin/python/python3 bin/python/python; do
    if [ -x "$root/$rel" ]; then echo "$root/$rel"; return 0; fi
  done
  return 1
}

if [ "$SOURCE_ONLY" -eq 0 ]; then
  if [ -z "$SOFA_ROOT" ]; then
    for c in "$HOME/.local/share/emio-labs/resources/sofa" "/opt/emio-labs/resources/sofa"; do
      [ -d "$c" ] && SOFA_ROOT="$c" && break
    done
  fi
  if [ -z "$SOFA_ROOT" ] || [ ! -d "$SOFA_ROOT" ]; then
    echo "ERROR: SOFA_ROOT not found. Pass it explicitly:" >&2
    echo "  tools/build_bundle.sh /path/to/emio-labs/resources/sofa" >&2
    exit 1
  fi
  SOFA_PY="$(find_sofa_python "$SOFA_ROOT")" || {
    echo "ERROR: bundled python not found under $SOFA_ROOT/bin/python" >&2; exit 1; }
  echo "Building with SOFA python: $SOFA_PY ($("$SOFA_PY" --version 2>&1))"
else
  echo "Building source-only patch (no dependencies)"
fi

# --- 1. Clean staging (zip root is the lab folder itself) -------------------
STAGE_ROOT="${TMPDIR:-/tmp}/lab_shapeOPT_bundle"
STAGE="$STAGE_ROOT/lab_shapeOPT"
rm -rf "$STAGE_ROOT"
mkdir -p "$STAGE"

# --- 2. Stage source from the working tree ----------------------------------
# git ls-files (cached + untracked-not-ignored) gives the real project files,
# so uncommitted edits ship and .venv / .git / caches are skipped.
cd "$LAB_ROOT"
SKIP_RE='^(\.venv/|dist/|tools/|runtime/modules/|runtime/(exports|logs|trials|recordings)/|runtime/.*\.(db|log)$|.*__pycache__/|.*\.pyc$|.*\.crproj$|failed_generation\.png$)'
count=0
while IFS= read -r f; do
  [[ "$f" =~ $SKIP_RE ]] && continue
  [ -f "$f" ] || continue
  mkdir -p "$STAGE/$(dirname "$f")"
  cp "$f" "$STAGE/$f"
  count=$((count + 1))
done < <(git ls-files --cached --others --exclude-standard)
echo "Staged $count source files"

# --- 2b. Stage runtime/recordings (required benchmark inputs) ---------------
if [ -d "$LAB_ROOT/runtime/recordings" ]; then
  mkdir -p "$STAGE/runtime"
  cp -r "$LAB_ROOT/runtime/recordings" "$STAGE/runtime/recordings"
  rec=$(find "$STAGE/runtime/recordings" -type f | wc -l)
  echo "Staged $rec recording file(s)"
fi

if [ "$SOURCE_ONLY" -eq 0 ]; then
  # --- 3. Install lab deps for Python 3.10 into the bundle site-packages -----
  BUNDLE_SP="$STAGE/runtime/modules/site-packages"
  mkdir -p "$BUNDLE_SP"
  echo "Installing dependencies into runtime/modules/site-packages ..."
  "$SOFA_PY" -m pip install --no-cache-dir --target "$BUNDLE_SP" -r "$REQUIREMENTS"

  # --- 4. Slim: caches and other-ABI compiled extensions --------------------
  find "$BUNDLE_SP" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find "$BUNDLE_SP" -type f -name '*.pyc' -delete 2>/dev/null || true
  # Keep cp310 only; drop other CPython ABI tags (Linux .so naming).
  find "$BUNDLE_SP" -type f \( \
      -name '*.cpython-311*.so' -o \
      -name '*.cpython-312*.so' -o \
      -name '*.cpython-313*.so' \) -delete 2>/dev/null || true

  # --- 4b. gmsh native lib --------------------------------------------------
  # gmsh ships its shared library as a wheel data file (.data/data/lib/), which
  # pip --target drops. Place it next to gmsh.py (gmsh.py's first search path).
  if [ -f "$BUNDLE_SP/gmsh.py" ]; then
    GMSH_SPEC="$(grep -E '^[[:space:]]*gmsh[[:space:]]*==' "$REQUIREMENTS" | tr -d '[:space:]')"
    GMSH_SPEC="${GMSH_SPEC:-gmsh}"
    WHEEL_DIR="$STAGE_ROOT/_gmsh_wheel"
    mkdir -p "$WHEEL_DIR"
    "$SOFA_PY" -m pip download "$GMSH_SPEC" --no-deps -q -d "$WHEEL_DIR"
    WHL="$(ls "$WHEEL_DIR"/gmsh-*.whl | head -1)"
    "$SOFA_PY" - "$WHL" "$BUNDLE_SP" <<'PY'
import os, posixpath, sys, zipfile
whl, dest = sys.argv[1], sys.argv[2]
z = zipfile.ZipFile(whl)
placed = False
for n in z.namelist():
    base = posixpath.basename(n)
    if base.startswith("libgmsh") and ".so" in base:
        with open(os.path.join(dest, base), "wb") as fh:
            fh.write(z.read(n))
        print("Placed gmsh native lib next to gmsh.py:", base)
        placed = True
if not placed:
    sys.exit("gmsh native .so not found in " + whl)
PY
  fi
fi

# --- 5. Zip -----------------------------------------------------------------
mkdir -p "$OUT_DIR"
if [ "$SOURCE_ONLY" -eq 1 ]; then
  ZIP="$OUT_DIR/lab_shapeOPT_source_linux.zip"
else
  ZIP="$OUT_DIR/lab_shapeOPT_bundle_linux.zip"
fi
rm -f "$ZIP"
echo "Compressing ..."
( cd "$STAGE_ROOT" && zip -rq "$ZIP" lab_shapeOPT )

echo ""
echo "Bundle written: $ZIP ($(du -h "$ZIP" | cut -f1))"
if [ "$SOURCE_ONLY" -eq 1 ]; then
  echo "Extract OVER an existing assets/labs/lab_shapeOPT to update the code (deps untouched)."
else
  echo "Unzip into <emio-labs>/.../assets/labs/ to get assets/labs/lab_shapeOPT."
fi
