"""Screen-space hit testing of the retopo mesh, with occlusion against the live surface."""

from mathutils import Vector

from . import geometry


def seg_param(p, a, b):
    """(t, distance) of point p against segment a-b; t is unclamped."""
    ab = b - a
    l2 = ab.length_squared
    if l2 < 1e-12:
        return 0.0, (p - a).length
    t = (p - a).dot(ab) / l2
    tc = min(max(t, 0.0), 1.0)
    return t, (p - (a + ab * tc)).length


def cross2(a, b):
    return a.x * b.y - a.y * b.x


def point_in_poly(p, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        a, b = pts[i], pts[j]
        if (a.y > p.y) != (b.y > p.y) and p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x:
            inside = not inside
        j = i
    return inside


class Picker:
    """Snapshot of the mesh's 2D layout for one event."""

    def __init__(self, region, rv3d, mw, bm, surface):
        self.region, self.rv3d, self.mw, self.bm, self.surface = region, rv3d, mw, bm, surface
        persp = rv3d.perspective_matrix @ mw
        hw, hh = region.width * 0.5, region.height * 0.5
        co2d = {}
        for v in bm.verts:
            if v.hide:
                continue
            q = persp @ v.co.to_4d()
            if q.w <= 1e-6:
                continue
            co2d[v] = Vector((hw + hw * q.x / q.w, hh + hh * q.y / q.w))
        self.co2d = co2d
        self._vis = {}

    def visible(self, v):
        r = self._vis.get(v)
        if r is None:
            c = self.co2d.get(v)
            r = c is not None and self.surface.is_visible(self.region, self.rv3d, self.mw @ v.co, c)
            self._vis[v] = r
        return r

    def verts_near(self, pos, radius, pred=None):
        """Visible verts within radius, nearest first, as (dist, vert)."""
        return [(d, v) for d, v in self._sorted_candidates(pos, radius, pred) if self.visible(v)]

    def nearest_vert(self, pos, radius, pred=None):
        for _d, v in self._sorted_candidates(pos, radius, pred):
            if self.visible(v):
                return v
        return None

    def _sorted_candidates(self, pos, radius, pred):
        out = []
        for v, c in self.co2d.items():
            d = (c - pos).length
            if d <= radius and (pred is None or pred(v)):
                out.append((d, v))
        out.sort(key=lambda x: x[0])
        return out

    def nearest_edge(self, pos, radius, pred=None):
        """(edge, t) of the closest visible edge beside the cursor; t runs from edge.verts[0]."""
        co2d = self.co2d
        best = []
        for e in self.bm.edges:
            if e.hide:
                continue
            a, b = e.verts
            pa, pb = co2d.get(a), co2d.get(b)
            if pa is None or pb is None:
                continue
            t, d = seg_param(pos, pa, pb)
            if d <= radius and 0.0 <= t <= 1.0 and (pred is None or pred(e)):
                best.append((d, t, e))
        best.sort(key=lambda x: x[0])
        for _d, t, e in best:
            if self.visible(e.verts[0]) and self.visible(e.verts[1]):
                return e, t
        return None, 0.0

    def face_under(self, pos):
        co2d = self.co2d
        view_origin = self.rv3d.view_matrix.inverted().translation
        best = None
        for f in self.bm.faces:
            if f.hide:
                continue
            pts = [co2d.get(v) for v in f.verts]
            if any(p is None for p in pts) or not point_in_poly(pos, pts):
                continue
            if not all(self.visible(v) for v in f.verts):
                continue
            depth = (self.mw @ f.calc_center_median() - view_origin).length
            if best is None or depth < best[0]:
                best = (depth, f)
        return best[1] if best else None

    def element(self, pos, radius):
        """Most specific element under the cursor: ('VERT'|'EDGE'|'FACE', elem) or None."""
        v = self.nearest_vert(pos, radius)
        if v is not None:
            return 'VERT', v
        e, _t = self.nearest_edge(pos, radius)
        if e is not None:
            return 'EDGE', e
        f = self.face_under(pos)
        if f is not None:
            return 'FACE', f
        return None

    def fill_candidate(self, pos, radius):
        """Verts for a Shift-click fill: (picks, border_edge) or (verts, None), or None."""
        co2d = self.co2d
        best = None
        for e in self.bm.edges:
            if e.hide or len(e.link_faces) != 1:
                continue
            a, b = e.verts
            pa, pb = co2d.get(a), co2d.get(b)
            if pa is None or pb is None:
                continue
            t, d = seg_param(pos, pa, pb)
            if d > radius or t < -0.2 or t > 1.2:
                continue
            pts = [co2d.get(x) for x in e.link_faces[0].verts]
            if any(p is None for p in pts):
                continue
            fc = sum(pts, Vector((0.0, 0.0))) / len(pts)
            sm, sf = cross2(pb - pa, pos - pa), cross2(pb - pa, fc - pa)
            if sm * sf >= 0:
                continue  # cursor is on the side that already has a face
            if not (self.visible(a) and self.visible(b)):
                continue
            if best is None or d < best[0]:
                best = (d, e, sm)

        if best is not None:
            _d, e, sm = best
            a, b = e.verts
            pa, pb = co2d[a], co2d[b]
            ab = (pb - pa)
            ab_len = max(ab.length, 1e-6)
            picks = []
            for _dist, v in self.verts_near(pos, radius * 1.5,
                                            pred=lambda v: v != a and v != b and geometry.is_open(v)):
                side = cross2(ab, co2d[v] - pa)
                if side * sm > 0 and abs(side) / ab_len > 4.0:
                    picks.append(v)
                    if len(picks) == 2:
                        break
            return (picks, e) if picks else None

        near = self.verts_near(pos, radius, pred=geometry.is_open)
        if len(near) >= 3:
            return [v for _d, v in near[:4]], None
        return None
