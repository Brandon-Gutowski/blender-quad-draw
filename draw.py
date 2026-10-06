"""Viewport overlay for the Quad Draw modal operator."""

import math

import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

CAGE_EDGE = (0.35, 0.75, 1.0, 1.0)
CAGE_FILL = (0.35, 0.75, 1.0, 0.12)

GREEN = (0.25, 1.0, 0.35, 1.0)
GREEN_FILL = (0.25, 1.0, 0.35, 0.18)
BLUE = (0.3, 0.65, 1.0, 1.0)
BLUE_FILL = (0.3, 0.65, 1.0, 0.3)
YELLOW = (1.0, 0.85, 0.15, 1.0)
RED = (1.0, 0.25, 0.25, 1.0)
RED_FILL = (1.0, 0.25, 0.25, 0.25)
DOT = (0.1, 0.9, 1.0, 1.0)
BRUSH = (1.0, 1.0, 1.0, 0.6)


class DrawData:
    """Plain world-space coordinates; never holds bmesh elements, so it can't go stale."""

    def __init__(self):
        self.clear()

        self.mesh = None   # dict(co=(n,3) world float32, edges=[(i,j)], tris=[(i,j,k)]), rebuilt on edits

    def clear(self):
        self.prims = []    # (kind 'TRIS'|'LINES'|'POINTS', coords, color, size)
        self.brush = None  # (center Vector2, radius)

    def add(self, kind, coords, color, size=1.0):
        if coords:
            self.prims.append((kind, coords, color, size))


def _is_our_region(op):
    region = bpy.context.region
    return region is not None and region.as_pointer() == op.region_ptr


def _visible_parts(op, mesh, region, rv3d):
    """Edges/tris whose verts the live surface doesn't hide; cached per view."""
    key = (tuple(tuple(r) for r in rv3d.perspective_matrix), region.width, region.height)
    if mesh.get("key") != key:
        vis = []
        for c in mesh["co"]:
            p = Vector(c)
            p2 = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
            vis.append(p2 is not None and op.surface.is_visible(region, rv3d, p, p2))
        mesh["edges_vis"] = [e for e in mesh["edges"] if vis[e[0]] and vis[e[1]]]
        mesh["tris_vis"] = [t for t in mesh["tris"] if vis[t[0]] and vis[t[1]] and vis[t[2]]]
        mesh["verts_vis"] = [i for i, ok in enumerate(vis) if ok]
        mesh["key"] = key
    return mesh["edges_vis"], mesh["tris_vis"], mesh["verts_vis"]


def _draw_cage(op, mesh, vp):
    region, rv3d = bpy.context.region, bpy.context.region_data
    if rv3d is None or not len(mesh["co"]):
        return
    edges, tris, verts = _visible_parts(op, mesh, region, rv3d)
    co = mesh["co"]
    if tris:
        sh = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(sh, 'TRIS', {"pos": co}, indices=tris)
        sh.bind()
        sh.uniform_float("color", CAGE_FILL)
        batch.draw(sh)
    if edges:
        sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        batch = batch_for_shader(sh, 'LINES', {"pos": co}, indices=edges)
        sh.bind()
        sh.uniform_float("viewportSize", (vp[2], vp[3]))
        sh.uniform_float("lineWidth", 1.5)
        sh.uniform_float("color", CAGE_EDGE)
        batch.draw(sh)
    if verts:
        sh = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')
        batch = batch_for_shader(sh, 'POINTS', {"pos": co[verts]})
        gpu.state.point_size_set(5.0)
        sh.bind()
        sh.uniform_float("color", CAGE_EDGE)
        batch.draw(sh)


def draw_3d(op):
    if not _is_our_region(op):
        return
    vp = gpu.state.viewport_get()
    gpu.state.blend_set('ALPHA')
    try:
        gpu.state.depth_test_set('NONE')
        if op.dd.mesh is not None:
            _draw_cage(op, op.dd.mesh, vp)
        for kind, coords, color, size in op.dd.prims:
            if kind == 'TRIS':
                sh = gpu.shader.from_builtin('UNIFORM_COLOR')
                batch = batch_for_shader(sh, 'TRIS', {"pos": coords})
                sh.bind()
                sh.uniform_float("color", color)
            elif kind == 'LINES':
                sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
                batch = batch_for_shader(sh, 'LINES', {"pos": coords})
                sh.bind()
                sh.uniform_float("viewportSize", (vp[2], vp[3]))
                sh.uniform_float("lineWidth", size)
                sh.uniform_float("color", color)
            else:
                sh = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')
                batch = batch_for_shader(sh, 'POINTS', {"pos": coords})
                gpu.state.point_size_set(size)
                sh.bind()
                sh.uniform_float("color", color)
            batch.draw(sh)
    finally:
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set('NONE')


def draw_2d(op):
    if not _is_our_region(op) or op.dd.brush is None:
        return
    (cx, cy), r = op.dd.brush
    segs = 48
    pts = [(cx + r * math.cos(2 * math.pi * i / segs), cy + r * math.sin(2 * math.pi * i / segs), 0.0)
           for i in range(segs + 1)]
    vp = gpu.state.viewport_get()
    sh = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    batch = batch_for_shader(sh, 'LINE_STRIP', {"pos": pts})
    gpu.state.blend_set('ALPHA')
    sh.bind()
    sh.uniform_float("viewportSize", (vp[2], vp[3]))
    sh.uniform_float("lineWidth", 1.5)
    sh.uniform_float("color", BRUSH)
    batch.draw(sh)
    gpu.state.blend_set('NONE')
