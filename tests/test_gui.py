import math, os, sys, traceback, faulthandler
import bpy, bmesh, addon_utils
from mathutils import Vector, Euler
from bpy_extras import view3d_utils

OUT = os.environ.get("QD_OUT", os.path.dirname(os.path.abspath(__file__)))
LOG = []
def log(*a):
    s = " ".join(str(x) for x in a); LOG.append(s); print(s, flush=True)

mod = "bl_ext.user_default.quad_draw"
try:
    bpy.ops.extensions.repo_refresh_all() if hasattr(bpy.ops.extensions, "repo_refresh_all") else None
except Exception:
    pass
addon_utils.enable(mod, default_set=True)
log("enabled:", mod in bpy.context.preferences.addons, "op:", hasattr(bpy.ops.mesh, "quad_draw"))

import importlib
opmod = importlib.import_module(mod + ".operator")
_orig = opmod.MESH_OT_quad_draw._modal
NEV=[0]
OPS=[]
def _logged(self, context, event):
    NEV[0]+=1
    r = _orig(self, context, event)
    if NEV[0] < 400 and event.type != 'MOUSEMOVE': log('  ev', event.type, event.value, r, self.state, 'mouse', tuple(round(c) for c in self.mouse))
    return r
opmod.MESH_OT_quad_draw._modal = _logged
_inv = opmod.MESH_OT_quad_draw.invoke
def _linv(self, c, e):
    OPS.append(self); r = _inv(self, c, e); log('  invoke', r); return r
opmod.MESH_OT_quad_draw.invoke = _linv
# scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1.0)
live = bpy.context.active_object
bpy.ops.object.shade_smooth()
bpy.context.scene.quad_draw.live_object = live
me = bpy.data.meshes.new("Retopo"); retopo = bpy.data.objects.new("Retopo", me)
bpy.context.collection.objects.link(retopo)
live.select_set(False); retopo.select_set(True)
bpy.context.view_layer.objects.active = retopo
bpy.ops.object.mode_set(mode='EDIT')

win = bpy.context.window_manager.windows[0]
area = max((a for a in win.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
region = next(r for r in area.regions if r.type == 'WINDOW')
space = area.spaces.active
rv3d = space.region_3d
space.overlay.show_retopology = True
rv3d.view_perspective = 'PERSP'
rv3d.view_rotation = Euler((math.radians(90), 0, 0)).to_quaternion()  # front view, looking +Y
rv3d.view_location = (0, 0, 0)
rv3d.view_distance = 3.2

def scr(world):
    p = view3d_utils.location_3d_to_region_2d(region, rv3d, Vector(world))
    return int(p.x + region.x), int(p.y + region.y)

def front(x, z):  # point on the sphere's front (-Y) side
    return (x, -math.sqrt(max(0.0, 1 - x * x - z * z)), z)

def ev(type, value, pos, **mods):
    win.event_simulate(type=type, value=value, x=pos[0], y=pos[1], **mods)

def click(pos, **mods):
    ev('MOUSEMOVE', 'NOTHING', pos, **mods)
    ev('LEFTMOUSE', 'PRESS', pos, **mods)
    ev('LEFTMOUSE', 'RELEASE', pos, **mods)

def drag(a, b, steps=8, **mods):
    ev('MOUSEMOVE', 'NOTHING', a, **mods)
    ev('LEFTMOUSE', 'PRESS', a, **mods)
    for i in range(1, steps + 1):
        t = i / steps
        ev('MOUSEMOVE', 'NOTHING', (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t)), **mods)
    ev('LEFTMOUSE', 'RELEASE', b, **mods)

def counts():
    bm = bmesh.from_edit_mesh(me)
    return len(bm.verts), len(bm.edges), len(bm.faces)

def on_surface(tol=3e-3):
    bm = bmesh.from_edit_mesh(me)
    return all(abs(v.co.length - 1) < tol for v in bm.verts)

def shot(name):
    path = os.path.join(OUT, name)
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=path)
    log("screenshot", name, "overlay:", [(k, len(c), col) for k, c, col, _ in OPS[-1].dd.prims] if OPS else None)

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); log("PASS" if cond else "FAIL", name, info)

s = 0.22
P = {k: front(*xz) for k, xz in dict(a=(-s, -s), b=(s, -s), c=(s, s), d=(-s, s)).items()}
centre = front(0, 0)

def steps():
    # start via keymap (Shift+Q) with the mouse over the viewport
    log('expected region-space a', [c - o for c, o in zip(scr(P['a']), (region.x, region.y))]); log('win', win.width, win.height, 'region', region.x, region.y, region.width, region.height, 'pts', scr(P['a']), scr(centre))
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.get('Mesh')
    log('addon km items', [(k.idname, k.type, k.shift) for k in km.keymap_items] if km else None)
    shot('qd_0_start.png')
    ev('MOUSEMOVE', 'NOTHING', scr(front(0.5, 0.5)))
    yield
    ev('LEFT_SHIFT', 'PRESS', scr(front(0.5, 0.5)), shift=True)
    ev('Q', 'PRESS', scr(front(0.5, 0.5)), shift=True); ev('Q', 'RELEASE', scr(front(0.5, 0.5)), shift=True)
    ev('LEFT_SHIFT', 'RELEASE', scr(front(0.5, 0.5)))
    yield
    for k in "abcd":
        click(scr(P[k]))
    yield
    check("4 dots", counts() == (4, 0, 0), counts())
    check("dots on surface", on_surface())
    # shift hover -> preview, then shift-click to fill
    ev('LEFT_SHIFT', 'PRESS', scr(centre), shift=True)
    ev('MOUSEMOVE', 'NOTHING', scr(centre), shift=True)
    yield
    yield
    shot("qd_1_fill_preview.png")
    click(scr(centre), shift=True)
    ev('LEFT_SHIFT', 'RELEASE', scr(centre))
    yield
    check("fill quad", counts() == (4, 4, 1), counts())
    # tab-drag the right border edge outward
    edge_mid = front(s, 0)
    ev('MOUSEMOVE', 'NOTHING', scr(edge_mid))
    ev('TAB', 'PRESS', scr(edge_mid))
    ev('MOUSEMOVE', 'NOTHING', scr(edge_mid))
    yield
    drag(scr(edge_mid), scr(front(s + 0.4, 0)))
    ev('TAB', 'RELEASE', scr(front(s + 0.4, 0)))
    yield
    check("extend", counts() == (6, 7, 2), counts())
    check("extend on surface", on_surface())
    # extend again from the new border edge, then the end should weld? (no target -> just 3 faces)
    # ctrl-click on the bottom edge of first quad -> loop through both quads
    bottom = front(0, -s)
    ev('LEFT_CTRL', 'PRESS', scr(bottom), ctrl=True)
    ev('MOUSEMOVE', 'NOTHING', scr(bottom), ctrl=True)
    yield
    yield
    shot("qd_2_loop_preview.png")
    click(scr(bottom), ctrl=True)
    ev('LEFT_CTRL', 'RELEASE', scr(bottom))
    yield
    v, e, f = counts()
    check("insert loop", f == 3, counts())
    # undo / redo
    ev('Z', 'PRESS', scr(bottom), ctrl=True); ev('Z', 'RELEASE', scr(bottom), ctrl=True)
    yield
    check("undo", counts()[2] == 2, counts())
    ev('Z', 'PRESS', scr(bottom), ctrl=True, shift=True); ev('Z', 'RELEASE', scr(bottom), ctrl=True, shift=True)
    yield
    check("redo", counts()[2] == 3, counts())
    # tweak a corner vert
    bm = bmesh.from_edit_mesh(me)
    before = sorted(tuple(round(c, 3) for c in v.co) for v in bm.verts)
    drag(scr(P['d']), scr(front(-s - 0.1, s + 0.1)))
    yield
    bm = bmesh.from_edit_mesh(me)
    after = sorted(tuple(round(c, 3) for c in v.co) for v in bm.verts)
    check("tweak moved vert", before != after and counts()[2] == 3)
    check("tweak on surface", on_surface())
    # relax brush
    ev('LEFT_SHIFT', 'PRESS', scr(centre), shift=True)
    drag(scr(front(-0.05, 0)), scr(front(0.1, 0.05)), shift=True)
    ev('LEFT_SHIFT', 'RELEASE', scr(centre))
    yield
    check("relax keeps topology", counts()[2] == 3, counts())
    check("relax on surface", on_surface())
    ev('MOUSEMOVE', 'NOTHING', scr(front(0.3, 0.3)))
    yield
    yield
    shot("qd_3_after_edits.png")
    # F brush resize: confirm with LMB, then cancel with Esc (must not exit the tool)
    st = bpy.context.scene.quad_draw
    r0 = st.brush_radius
    m = scr(front(-0.5, -0.5))
    ev('MOUSEMOVE', 'NOTHING', m)
    ev('F', 'PRESS', m); ev('F', 'RELEASE', m)
    ev('MOUSEMOVE', 'NOTHING', (m[0] + 100, m[1]))
    ev('LEFTMOUSE', 'PRESS', (m[0] + 100, m[1])); ev('LEFTMOUSE', 'RELEASE', (m[0] + 100, m[1]))
    yield
    r1 = st.brush_radius
    check("F resize confirm", r1 > r0, f"{r0}->{r1}")
    check("F confirm placed no dot", counts()[2] == 3 and counts()[0] == 8, counts())
    ev('F', 'PRESS', m); ev('F', 'RELEASE', m)
    ev('MOUSEMOVE', 'NOTHING', (m[0] + 300, m[1]))
    ev('ESC', 'PRESS', m); ev('ESC', 'RELEASE', m)
    yield
    check("F resize cancel", st.brush_radius == r1, st.brush_radius)
    check("tool still running after cancel", OPS[-1].state == 'IDLE' and OPS[-1]._handles)
    # delete a face (hover inside extended quad)
    inside = front(s + 0.2, 0.05)
    ev('LEFT_CTRL', 'PRESS', scr(inside), ctrl=True)
    click(scr(inside), ctrl=True, shift=True)
    ev('LEFT_CTRL', 'RELEASE', scr(inside))
    yield
    check("delete face", counts()[2] == 2, counts())
    # finish
    ev('ESC', 'PRESS', scr(inside)); ev('ESC', 'RELEASE', scr(inside))
    yield
    check("exited to edit mode", bpy.context.object.mode == 'EDIT')
    log(f"{sum(results)}/{len(results)} passed")

gen = steps()
TICK=[0]
def tick():
    TICK[0]+=1; log('tick', TICK[0], 'counts', counts(), 'mode', bpy.context.mode)
    if TICK[0] > 40: gen.close()
    try:
        next(gen)
        return 0.4
    except StopIteration:
        pass
    except Exception:
        log(traceback.format_exc())
    with open(os.path.join(OUT, "gui_log.txt"), "w") as fh:
        fh.write("\n".join(LOG))
    bpy.ops.wm.quit_blender()
    return None

bpy.app.timers.register(tick, first_interval=1.5)
