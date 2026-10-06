"""MESH_OT_quad_draw: the modal Quad Draw tool."""

import traceback

import bmesh
import bpy
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector

from . import draw, geometry
from .picking import Picker
from .prefs import get_prefs
from .surface import LiveSurface

PASS_EVENTS = {
    'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
    'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM', 'TIMER', 'TIMER_REPORT',
}
MOD_KEYS = {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT', 'OSKEY'}
MAX_UNDO = 64

STATUS = ("Quad Draw  |  LMB: dot · drag: tweak  |  Shift+LMB: fill quad · drag: relax  |  "
          "Tab+drag border edge: extend  |  Ctrl+LMB: insert loop  |  Ctrl+Shift+LMB: delete  |  "
          "F: brush size  |  Ctrl/Cmd+Z: undo  |  Esc/RMB/Enter: finish")


class MESH_OT_quad_draw(bpy.types.Operator):
    """Draw retopology quads onto the live surface (Maya-style Quad Draw)"""
    bl_idname = "mesh.quad_draw"
    bl_label = "Quad Draw"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        obj = context.edit_object
        return (context.mode == 'EDIT_MESH' and obj is not None and obj.type == 'MESH'
                and context.area is not None and context.area.type == 'VIEW_3D')

    # --- lifecycle -------------------------------------------------------------

    def invoke(self, context, event):
        obj = context.edit_object
        settings = context.scene.quad_draw
        live = settings.live_object
        if live is not None and (live == obj or live.type != 'MESH'):
            self.report({'ERROR'}, "The live surface must be a different mesh object")
            return {'CANCELLED'}

        self.area = context.area
        self.region = next((r for r in self.area.regions if r.type == 'WINDOW'), None)
        self.rv3d = self.area.spaces.active.region_3d
        if self.region is None or self.rv3d is None:
            return {'CANCELLED'}
        self.region_ptr = self.region.as_pointer()

        self.obj, self.me = obj, obj.data
        self.mw = obj.matrix_world.copy()
        self.imw = self.mw.inverted()
        self.bm = bmesh.from_edit_mesh(self.me)
        self.surface = LiveSurface(live, context.evaluated_depsgraph_get(), obj)
        if live is None:
            self.report({'WARNING'}, "No live surface set: drawing on the view plane")
        self.settings = settings
        self.prefs = get_prefs(context)
        self.cursor_loc = context.scene.cursor.location.copy()
        self.px = context.preferences.system.pixel_size  # 2 on Retina: settings are in UI points

        self.state = 'IDLE'
        self.shift = self.ctrl = self.tab_down = False
        self.mouse = self._mouse(event)
        self.press = None
        self.hover = None
        self.undo_stack, self.redo_stack = [], []
        self.dd = draw.DrawData()
        self.build_cage()

        self._handles = [
            bpy.types.SpaceView3D.draw_handler_add(draw.draw_3d, (self,), 'WINDOW', 'POST_VIEW'),
            bpy.types.SpaceView3D.draw_handler_add(draw.draw_2d, (self,), 'WINDOW', 'POST_PIXEL'),
        ]
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(STATUS)
        self.refresh()
        self.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def finish(self, context):
        for h in getattr(self, "_handles", []):
            bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
        self._handles = []
        for snap in self.undo_stack + self.redo_stack:
            snap.free()
        self.undo_stack, self.redo_stack = [], []
        if context.workspace:
            context.workspace.status_text_set(None)
        if self.bm.is_valid:
            self.commit(topo=True)
        self.area.tag_redraw()

    def cancel(self, context):
        self.finish(context)

    def modal(self, context, event):
        try:
            return self._modal(context, event)
        except Exception:
            traceback.print_exc()
            self.report({'ERROR'}, "Quad Draw hit an error and stopped (see console)")
            self.finish(context)
            return {'FINISHED'}

    # --- helpers ----------------------------------------------------------------

    def _mouse(self, event):
        return Vector((event.mouse_x - self.region.x, event.mouse_y - self.region.y))

    def _in_region(self):
        return 0 <= self.mouse.x < self.region.width and 0 <= self.mouse.y < self.region.height

    @property
    def pick_px(self):
        return self.prefs.pick_radius * self.px

    @property
    def brush_px(self):
        return self.settings.brush_radius * self.px

    def picker(self):
        return Picker(self.region, self.rv3d, self.mw, self.bm, self.surface)

    def project(self, co):
        return self.surface.project_local(co)

    def view_normal_local(self):
        n = self.rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
        return (self.mw.to_3x3().transposed() @ n).normalized()

    def surface_normal(self, verts):
        c = sum((v.co for v in verts), Vector()) / len(verts)
        return self.surface.normal_local(c, self.view_normal_local())

    def ray_hit(self, mouse):
        o = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, mouse)
        d = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, mouse)
        return self.surface.ray(o, d)

    def plane_hit(self, mouse, depth):
        return view3d_utils.region_2d_to_location_3d(self.region, self.rv3d, mouse, depth)

    def commit(self, topo):
        bmesh.update_edit_mesh(self.me, loop_triangles=True, destructive=topo)
        self.build_cage()

    def build_cage(self):
        bm = self.bm
        bm.verts.index_update()
        co = np.array([v.co for v in bm.verts], dtype=np.float32).reshape(-1, 3)
        m = np.array(self.mw, dtype=np.float32)
        co = co @ m[:3, :3].T + m[:3, 3]
        edges = [(e.verts[0].index, e.verts[1].index) for e in bm.edges if not e.hide]
        tris = []
        for f in bm.faces:
            if f.hide:
                continue
            idx = [v.index for v in f.verts]
            tris.extend((idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1))
        self.dd.mesh = dict(co=co, edges=edges, tris=tris)

    def snapshot(self):
        self.undo_stack.append(self.bm.copy())
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0).free()
        for snap in self.redo_stack:
            snap.free()
        self.redo_stack = []

    def restore(self, src, dst):
        if not src:
            return
        dst.append(self.bm.copy())
        snap = src.pop()
        tmp = bpy.data.meshes.new("_quad_draw_tmp")
        try:
            snap.to_mesh(tmp)
            self.bm.clear()
            self.bm.from_mesh(tmp)
        finally:
            snap.free()
            bpy.data.meshes.remove(tmp)
        self.commit(topo=True)

    # --- event dispatch ---------------------------------------------------------

    def _modal(self, context, event):
        t, v = event.type, event.value
        self.area.tag_redraw()

        if self.state == 'BRUSH':
            return self.brush_modal(event)

        if v == 'PRESS' and (t in {'ESC', 'RET', 'NUMPAD_ENTER'} or (t == 'RIGHTMOUSE' and self.state == 'IDLE')):
            self.finish(context)
            return {'FINISHED'}
        if t in PASS_EVENTS or t.startswith('NDOF') or t.startswith('NUMPAD'):
            return {'PASS_THROUGH'}

        if not self.bm.is_valid:
            self.bm = bmesh.from_edit_mesh(self.me)
        self.shift, self.ctrl = event.shift, event.ctrl
        self.mouse = self._mouse(event)

        # Let the sidebar/header work while idle (e.g. tweak brush settings).
        if self.state == 'IDLE' and not self._in_region() and t in {'LEFTMOUSE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.hover = None
            self.dd.clear()
            return {'PASS_THROUGH'}

        if t == 'Z' and v == 'PRESS' and (event.ctrl or event.oskey):
            if event.shift:
                self.restore(self.redo_stack, self.undo_stack)
            else:
                self.restore(self.undo_stack, self.redo_stack)
            self.state = 'IDLE'
            self.shift = self.ctrl = False
        elif t == 'TAB':
            if v == 'PRESS':
                self.tab_down = True
            elif v == 'RELEASE':
                self.tab_down = False
        elif t == 'F' and v == 'PRESS' and self.state == 'IDLE':
            # Like Blender's radial control: the cursor starts on the circle's edge.
            self.state = 'BRUSH'
            self.brush_start = (self.mouse - Vector((self.brush_px, 0.0)), self.settings.brush_radius)
        elif t in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.on_move()
        elif t == 'LEFTMOUSE':
            if v == 'PRESS':
                self.on_press()
            elif v == 'RELEASE':
                self.on_release()
        elif t not in MOD_KEYS:
            return {'RUNNING_MODAL'}

        self.refresh()
        return {'RUNNING_MODAL'}

    def brush_modal(self, event):
        """F resize: move to size, LMB/Enter/Space confirm, RMB/Esc cancel."""
        t, v = event.type, event.value
        center, r0 = self.brush_start
        self.mouse = self._mouse(event)
        if t in PASS_EVENTS or t.startswith('NDOF'):
            return {'PASS_THROUGH'}
        if t in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.settings.brush_radius = max(5, int((self.mouse - center).length / self.px))
        elif v == 'PRESS' and t in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER', 'SPACE'}:
            self.state = 'IDLE'
        elif v == 'PRESS' and t in {'RIGHTMOUSE', 'ESC'}:
            self.settings.brush_radius = r0
            self.state = 'IDLE'
        self.refresh()
        return {'RUNNING_MODAL'}

    # --- hover / preview --------------------------------------------------------

    def refresh(self):
        """Recompute what's under the cursor and rebuild the overlay."""
        dd = self.dd
        dd.clear()
        self.hover = None
        if not self.bm.is_valid:
            return
        mw = self.mw
        dd.add('POINTS', [mw @ v.co for v in self.bm.verts if not v.hide and not v.link_edges], draw.DOT, 7.0)

        st = self.state
        if st == 'BRUSH':
            dd.brush = (self.brush_start[0], self.brush_px)
            return
        if st == 'RELAX' or (st == 'IDLE' and self.shift and not self.ctrl):
            dd.brush = (self.mouse, self.brush_px)
        if st != 'IDLE' or not self._in_region():
            return

        p = self.picker()
        r = self.pick_px
        if self.shift and self.ctrl:
            self.hover = p.element(self.mouse, r)
            self._draw_element(self.hover, draw.RED, draw.RED_FILL, delete=True)
        elif self.ctrl:
            e, t = p.nearest_edge(self.mouse, r * 2)
            if e is not None:
                ring, closed = geometry.edge_ring(e, e.verts[0])
                if len(ring) >= 2:
                    t = min(max(t, 0.05), 0.95)
                    pts = [mw @ self.project(s.co.lerp(ed.other_vert(s).co, t)) for ed, s in ring]
                    segs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if closed else [])
                    dd.add('LINES', [c for seg in segs for c in seg], draw.YELLOW, 2.5)
                    self.hover = ('EDGE', e)
        elif self.shift:
            order = self.fill_order(p)
            if order:
                cos = [mw @ v.co for v in order]
                tris = [c for i in range(1, len(cos) - 1) for c in (cos[0], cos[i], cos[i + 1])]
                dd.add('TRIS', tris, draw.BLUE_FILL)
                dd.add('LINES', [c for i in range(len(cos)) for c in (cos[i], cos[(i + 1) % len(cos)])],
                       draw.BLUE, 2.5)
        elif self.tab_down:
            e, _t = p.nearest_edge(self.mouse, r * 1.5, pred=lambda e: len(e.link_faces) <= 1)
            if e is not None:
                self.hover = ('EDGE', e)
                self._draw_element(self.hover, draw.YELLOW, draw.GREEN_FILL)
        else:
            self.hover = p.element(self.mouse, r)
            self._draw_element(self.hover, draw.GREEN, draw.GREEN_FILL)

    def _draw_element(self, hover, color, fill, delete=False):
        if hover is None:
            return
        kind, elem = hover
        mw, dd = self.mw, self.dd
        if kind == 'VERT':
            dd.add('POINTS', [mw @ elem.co], color, 12.0)
        elif kind == 'EDGE':
            edges = geometry.edge_loop(elem) if delete else [elem]
            dd.add('LINES', [mw @ v.co for e in edges for v in e.verts], color, 3.5)
        elif kind == 'FACE':
            cos = [mw @ v.co for v in elem.verts]
            dd.add('TRIS', [c for i in range(1, len(cos) - 1) for c in (cos[0], cos[i], cos[i + 1])], fill)
            dd.add('LINES', [c for i in range(len(cos)) for c in (cos[i], cos[(i + 1) % len(cos)])], color, 2.0)

    def fill_order(self, picker):
        """Ordered verts of the face a Shift-click would create, or None."""
        cand = picker.fill_candidate(self.mouse, self.prefs.fill_radius * self.px)
        if not cand:
            return None
        verts, edge = cand
        if edge is not None:
            order = geometry.order_from_edge(edge, verts)
        else:
            order = geometry.order_by_normal(verts, self.surface_normal(verts))
            order = geometry.fix_winding(self.bm, order)
        return order if geometry.can_make_face(self.bm, order) else None

    # --- mouse actions ----------------------------------------------------------

    def _moved(self):
        return self.press is not None and (self.mouse - self.press).length > self.prefs.drag_threshold * self.px

    def on_press(self):
        if self.state != 'IDLE':
            return
        self.press = self.mouse.copy()
        if self.shift and self.ctrl:
            self.state = 'P_DELETE'
        elif self.ctrl:
            self.state = 'P_LOOP'
        elif self.shift:
            self.state = 'P_SHIFT'
        elif self.tab_down:
            if self.hover and self.hover[0] == 'EDGE' and len(self.hover[1].link_faces) <= 1:
                self.ext = {'edge': self.hover[1], 'face': None}
                self.state = 'EXTEND'
        elif self.hover is not None:
            self.tweak_elem = self.hover
            self.state = 'P_TWEAK'
        else:
            self.state = 'P_DOT'

    def on_move(self):
        st = self.state
        if st == 'P_SHIFT' and self._moved():
            self.snapshot()
            self.state = 'RELAX'
            self.relax_step()
        elif st == 'RELAX':
            self.relax_step()
        elif st == 'P_TWEAK' and self._moved():
            self.start_tweak()
        elif st == 'TWEAK':
            self.tweak_step()
        elif st == 'EXTEND':
            self.extend_step()

    def on_release(self):
        st = self.state
        self.state = 'IDLE'
        p = self.picker()
        r = self.pick_px
        if st == 'P_DOT':
            hit = self.ray_hit(self.mouse)
            if hit is None and self.surface.bvh is None:
                hit = self.plane_hit(self.mouse, self.cursor_loc)
            if hit is not None:
                self.snapshot()
                self.bm.verts.new(self.imw @ hit)
                self.commit(topo=True)
        elif st == 'P_SHIFT':
            order = self.fill_order(p)
            if order:
                self.snapshot()
                geometry.make_face(self.bm, order)
                self.commit(topo=True)
        elif st == 'P_LOOP':
            e, t = p.nearest_edge(self.mouse, r * 2)
            if e is not None and len(geometry.edge_ring(e, e.verts[0])[0]) >= 2:
                self.snapshot()
                geometry.insert_loop(self.bm, e, e.verts[0], min(max(t, 0.05), 0.95), self.project)
                self.commit(topo=True)
        elif st == 'P_DELETE':
            hit = p.element(self.mouse, r)
            if hit is not None:
                self.snapshot()
                geometry.delete_element(self.bm, *hit)
                self.commit(topo=True)
        elif st == 'TWEAK':
            self.end_tweak(p)
        elif st == 'EXTEND':
            self.end_extend(p)
        self.press = None

    # tweak

    def start_tweak(self):
        kind, elem = self.tweak_elem
        if not elem.is_valid:
            self.state = 'IDLE'
            return
        verts = [elem] if kind == 'VERT' else list(elem.verts)
        self.snapshot()
        self.tw_verts = verts
        self.tw_orig = [self.mw @ v.co for v in verts]
        self.tw_center = sum(self.tw_orig, Vector()) / len(verts)
        self.tw_anchor = self.ray_hit(self.press) or self.plane_hit(self.press, self.tw_center)
        self.state = 'TWEAK'
        self.tweak_step()

    def tweak_step(self):
        if len(self.tw_verts) == 1:
            hit = self.ray_hit(self.mouse) or self.plane_hit(self.mouse, self.tw_orig[0])
            self.tw_verts[0].co = self.project(self.imw @ hit)
        else:
            hit = self.ray_hit(self.mouse) or self.plane_hit(self.mouse, self.tw_center)
            delta = hit - self.tw_anchor
            for v, w in zip(self.tw_verts, self.tw_orig):
                v.co = self.project(self.imw @ (w + delta))
        self.commit(topo=False)

    def end_tweak(self, p):
        if len(self.tw_verts) != 1 or not self.prefs.auto_weld:
            return
        v = self.tw_verts[0]
        c = p.co2d.get(v)
        if c is None:
            return
        target = p.nearest_vert(c, self.pick_px, pred=lambda x: x != v)
        if target is not None:
            geometry.weld(self.bm, {v: target})
            self.commit(topo=True)

    # extend

    def extend_step(self):
        ext = self.ext
        if ext['face'] is None:
            e = ext['edge']
            if not self._moved() or not e.is_valid:
                return
            self.snapshot()
            was_wire = not e.link_faces
            a, b = (self.mw @ x.co for x in e.verts)
            mid = (a + b) * 0.5
            hit = self.ray_hit(self.mouse) or self.plane_hit(self.mouse, mid)
            offset = self.imw.to_3x3() @ (hit - mid)
            f, x, y, nx, ny = geometry.extend_edge(self.bm, e, offset, self.project)
            ext.update(face=f, nx=nx, ny=ny, xw=self.mw @ x.co, yw=self.mw @ y.co, mid=mid, wire=was_wire)
            self.commit(topo=True)
            return
        hit = self.ray_hit(self.mouse) or self.plane_hit(self.mouse, ext['mid'])
        delta = hit - ext['mid']
        ext['nx'].co = self.project(self.imw @ (ext['xw'] + delta))
        ext['ny'].co = self.project(self.imw @ (ext['yw'] + delta))
        self.commit(topo=False)

    def end_extend(self, p):
        ext = self.ext
        f = ext['face']
        if f is None:
            return
        if ext['wire'] and f.is_valid:
            f.normal_update()
            if f.normal.dot(self.surface_normal(list(f.verts))) < 0:
                f.normal_flip()
        exclude = set(f.verts)
        targets = {}
        for nv in (ext['nx'], ext['ny']):
            c = p.co2d.get(nv)
            if c is None:
                continue
            tgt = p.nearest_vert(c, self.pick_px,
                                 pred=lambda x: x not in exclude and geometry.is_open(x)
                                 and x not in targets.values())
            if tgt is not None:
                targets[nv] = tgt
        if targets:
            geometry.weld(self.bm, targets)
        self.commit(topo=True)

    # relax

    def relax_step(self):
        p = self.picker()
        radius = self.brush_px
        weights = {}
        for v, c in p.co2d.items():
            d = (c - self.mouse).length
            if d < radius and v.link_edges and p.visible(v):
                weights[v] = (1.0 - (d / radius) ** 2) ** 2
        if weights:
            geometry.relax(weights, self.settings.relax_strength, self.project)
            self.commit(topo=False)
