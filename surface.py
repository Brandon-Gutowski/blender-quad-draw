"""The "live" reference surface everything snaps to."""

import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils


class LiveSurface:
    """World-space BVH of the live object; converts to/from the retopo object's local space.

    With no live object, projection is the identity and ray casts miss, so the tool
    falls back to drawing on the view plane.
    """

    def __init__(self, live_obj, depsgraph, target_obj):
        self.bvh = None
        self.eps = 1e-4
        self.mw = target_obj.matrix_world.copy()
        self.imw = self.mw.inverted()
        self.nmat = self.mw.to_3x3().transposed()  # world normal -> local normal
        if live_obj is not None:
            self._build(live_obj, depsgraph)

    def _build(self, live_obj, depsgraph):
        ev = live_obj.evaluated_get(depsgraph)
        me = ev.to_mesh()
        try:
            n = len(me.vertices)
            co = np.empty(n * 3, dtype=np.float32)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            m = np.array(live_obj.matrix_world, dtype=np.float64)
            co = co @ m[:3, :3].T + m[:3, 3]
            if hasattr(me, "calc_loop_triangles"):
                me.calc_loop_triangles()
            tris = np.empty(len(me.loop_triangles) * 3, dtype=np.int32)
            me.loop_triangles.foreach_get("vertices", tris)
        finally:
            ev.to_mesh_clear()
        if len(tris) == 0:
            return
        self.bvh = BVHTree.FromPolygons(co.tolist(), tris.reshape(-1, 3).tolist(), all_triangles=True)
        diag = float(np.linalg.norm(co.max(axis=0) - co.min(axis=0)))
        self.eps = max(diag * 0.004, 1e-5)

    # --- queries -------------------------------------------------------------

    def ray(self, origin, direction):
        """World-space hit point of a ray, or None."""
        if self.bvh is None:
            return None
        loc, _n, _i, _d = self.bvh.ray_cast(origin, direction)
        return loc

    def project_local(self, co):
        """Snap a retopo-local coordinate onto the surface (returns local)."""
        if self.bvh is None:
            return co.copy()
        loc, _n, _i, _d = self.bvh.find_nearest(self.mw @ co)
        return co.copy() if loc is None else self.imw @ loc

    def normal_local(self, co, fallback):
        """Outward surface normal near a local coordinate, in local space."""
        if self.bvh is not None:
            loc, n, _i, _d = self.bvh.find_nearest(self.mw @ co)
            if loc is not None:
                return (self.nmat @ n).normalized()
        return fallback

    def is_visible(self, region, rv3d, world_co, co2d):
        """False when the live surface occludes world_co from the viewer."""
        if self.bvh is None:
            return True
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, co2d)
        d = world_co - origin
        dist = d.length
        if dist < 1e-9:
            return True
        loc, _n, _i, hit_dist = self.bvh.ray_cast(origin, d / dist, dist)
        return loc is None or hit_dist >= dist - self.eps
