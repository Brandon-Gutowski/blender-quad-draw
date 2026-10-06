# Quad Draw for Blender

A Maya-style Quad Draw retopology tool for Blender 4.2+ (built and tested on 5.2).

## Install
**From a zip:** on GitHub use **Code → Download ZIP**, then in Blender
**Edit → Preferences → Add-ons → ▾ (top right) → Install from Disk…** and pick the zip.

**From a clone (easy to update with `git pull`):** clone the repo, then symlink it into
Blender's user extensions folder as `quad_draw` and restart Blender:
```bash
git clone https://github.com/Brandon-Gutowski/blender-quad-draw.git
```
- macOS: `~/Library/Application Support/Blender/<version>/extensions/user_default/quad_draw`
- Windows: `%APPDATA%\Blender Foundation\Blender\<version>\extensions\user_default\quad_draw`
  (`mklink /D` from an admin prompt)
- Linux: `~/.config/blender/<version>/extensions/user_default/quad_draw`

Then enable **Quad Draw** in **Preferences → Add-ons**.

## Use
1. Select your high-res mesh → sidebar (N) → **Quad Draw** tab → **Set Live Surface**.
2. **New Retopo Mesh** creates an empty mesh, enters Edit Mode and starts the tool.
   Or, in Edit Mode on any mesh, press **Shift+Q** / click **Quad Draw**.

| Input | Action |
|---|---|
| LMB click on surface | Place a dot |
| LMB drag on vert / edge / face | Tweak (stays on the surface; a dragged vert welds onto a vert it's dropped on) |
| Shift (hover) | Preview the quad from nearby dots / border edge |
| Shift+LMB click | Create that quad (or triangle) |
| Shift+LMB drag | Relax brush |
| Tab+LMB drag on border edge | Extend a new quad off the edge (new verts weld to nearby open verts) |
| Ctrl (hover) / Ctrl+LMB | Preview / insert an edge loop |
| Ctrl+Shift+LMB | Delete vert / face, or dissolve the edge loop under the cursor |
| F, move mouse, click | Resize brush (Esc / RMB cancels), like Blender's sculpt brushes |
| Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z | Undo / redo inside the tool |
| Esc / RMB / Enter | Finish (the whole session is one Blender undo step) |

Pixel radii live in the add-on preferences; brush radius and relax strength are in the sidebar.

## Tests
```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python QuadDraw/tests/test_geometry.py
```
`tests/test_gui.py` drives the real modal tool with simulated input (needs a GUI session and a .blend so no splash shows):
```bash
/Applications/Blender.app/Contents/MacOS/Blender --factory-startup --enable-event-simulate some_empty.blend --python QuadDraw/tests/test_gui.py
```
