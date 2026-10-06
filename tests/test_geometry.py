import sys, traceback
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import bpy, bmesh
from mathutils import Vector
import QuadDraw
from QuadDraw import geometry
from QuadDraw.surface import LiveSurface

results = []
def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), name, info)

QuadDraw.register()
check("register", hasattr(bpy.types.Scene, "quad_draw") and hasattr(bpy.ops.mesh, "quad_draw"))

bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1.0)
live = bpy.context.active_object
retopo = bpy.data.objects.new("R", bpy.data.meshes.new("R"))
bpy.context.collection.objects.link(retopo)
retopo.location = (0.3, 0, 0)          # non-identity transform
bpy.context.view_layer.update()
surf = LiveSurface(live, bpy.context.evaluated_depsgraph_get(), retopo)
proj = surf.project_local

def on_surface(bm, tol=2e-3):
    return all(abs((retopo.matrix_world @ v.co).length - 1.0) < tol for v in bm.verts)

def outward(f):
    c = retopo.matrix_world @ f.calc_center_median()
    return f.normal.dot(c) > 0  # rotation-free matrix, so local normal == world normal

bm = bmesh.new()
def dot(x, y, z):
    return bm.verts.new(proj(retopo.matrix_world.inverted() @ Vector((x, y, z))))

# 4 dots -> fill quad (given in scrambled order)
d = [dot(-.2, -.2, 1), dot(.2, .2, 1), dot(.2, -.2, 1), dot(-.2, .2, 1)]
n = surf.normal_local(sum((v.co for v in d), Vector()) / 4, Vector((0, 0, 1)))
order = geometry.fix_winding(bm, geometry.order_by_normal(d, n))
f = geometry.make_face(bm, order)
check("fill quad", f is not None and len(bm.faces) == 1)
check("fill on surface", on_surface(bm))
check("fill outward", outward(f))
check("duplicate rejected", not geometry.can_make_face(bm, order))

# extend off a border edge (+x side)
edge = max(f.edges, key=lambda e: sum(v.co.x for v in e.verts))
f2, x, y, nx, ny = geometry.extend_edge(bm, edge, Vector((0.4, 0, 0)), proj)
check("extend", len(bm.faces) == 2 and len(f2.verts) == 4)
check("extend shares edge", len(edge.link_faces) == 2)
check("extend outward", outward(f2))
check("extend on surface", on_surface(bm))

# fill off border edge with 2 picks
edge3 = max([e for e in bm.edges if e.is_boundary], key=lambda e: sum(v.co.y for v in e.verts) / 2 + 0 * 1)
edge3 = [e for e in f.edges if e.is_boundary and all(v.co.y > 0.1 for v in e.verts)][0]
p1, p2 = dot(-.2, .6, .8), dot(.2, .6, .8)
order = geometry.order_from_edge(edge3, [p2, p1])
f3 = geometry.make_face(bm, order)
check("edge fill", f3 is not None and len(bm.faces) == 3)
check("edge fill outward", outward(f3))
check("edge fill non-twisted", abs(f3.calc_area() - f.calc_area()) < f.calc_area())

# insert loop through the first quad's x-edge ring (should cut f and f2)
ring_edge = [e for e in f.edges if e in f2.edges][0]
cross = [e for e in f.edges if e != ring_edge and not (set(e.verts) & set(ring_edge.verts)) == False][0]
cross = [e for e in f.edges if len(set(e.verts) & set(ring_edge.verts)) == 1 and e not in f3.edges][0]
ring, closed = geometry.edge_ring(cross, cross.verts[0])
check("ring length", len(ring) == 3, f"len={len(ring)}")  # f's edge, shared edge, f2 far edge
nf = len(bm.faces)
new = geometry.insert_loop(bm, cross, cross.verts[0], 0.5, proj)
check("insert loop", len(new) == 3 and len(bm.faces) == nf + 2, f"faces={len(bm.faces)}")
check("loop on surface", on_surface(bm))
check("all quads", all(len(x.verts) == 4 for x in bm.faces))

# delete edge loop we just added -> back to previous face count
loop_edge = [e for e in bm.edges if set(e.verts) <= set(new) and len(e.link_faces) == 2][0]
geometry.delete_element(bm, 'EDGE', loop_edge)
check("delete edge loop", len(bm.faces) == nf, f"faces={len(bm.faces)} verts={len(bm.verts)}")

# relax: 3x3 grid on sphere, jitter centre
bm2 = bmesh.new()
grid = {}
for i in range(3):
    for j in range(3):
        grid[i, j] = bm2.verts.new(proj(retopo.matrix_world.inverted() @ Vector((-.3 + .3 * i, -.3 + .3 * j, 1))))
for i in range(2):
    for j in range(2):
        bm2.faces.new([grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]])
c = grid[1, 1]
target = sum((grid[a].co for a in [(0, 1), (2, 1), (1, 0), (1, 2)]), Vector()) / 4; target = proj(target)
c.co = proj(c.co + Vector((0.12, 0.1, 0)))
before = (c.co - target).length
for _ in range(10):
    geometry.relax({c: 1.0}, 0.5, proj)
after = (c.co - target).length
check("relax converges", after < before * 0.2, f"{before:.4f}->{after:.4f}")
bm = bm2
check("relax on surface", on_surface(bm2))
corner = grid[0, 0]
cc = corner.co.copy()
geometry.relax({corner: 1.0}, 1.0, proj)
check("corner pinned", (corner.co - cc).length < 1e-6)

# delete face
geometry.delete_element(bm2, 'FACE', bm2.faces[:][0] if False else list(bm2.faces)[0])
check("delete face", len(bm2.faces) == 3)

# edit-mode snapshot restore (what the modal undo does)
bpy.context.view_layer.objects.active = retopo
retopo.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
ebm = bmesh.from_edit_mesh(retopo.data)
ebm.verts.new((0, 0, 0)); ebm.verts.new((1, 0, 0))
snap = ebm.copy()
ebm.verts.new((2, 0, 0))
bmesh.update_edit_mesh(retopo.data)
tmp = bpy.data.meshes.new("tmp"); snap.to_mesh(tmp); snap.free()
ebm.clear(); ebm.from_mesh(tmp); bpy.data.meshes.remove(tmp)
bmesh.update_edit_mesh(retopo.data)
check("edit-mode restore", len(bmesh.from_edit_mesh(retopo.data).verts) == 2)
bpy.ops.object.mode_set(mode='OBJECT')

QuadDraw.unregister()
check("unregister", not hasattr(bpy.types.Scene, "quad_draw"))

fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} passed", "FAILED: " + ", ".join(fails) if fails else "")
