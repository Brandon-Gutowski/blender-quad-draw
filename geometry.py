"""bmesh operations for Quad Draw. All coordinates are in the retopo object's local space.

`project` arguments are callables mapping a local Vector onto the live surface.
"""

import math

import bmesh
from mathutils import Vector

CORNER_ANGLE = math.radians(135.0)  # border verts sharper than this are pinned while relaxing


def is_open(v):
    """A vert a new face may use: a loose dot, wire vert, or on the mesh border."""
    return not v.hide and (not v.link_faces or v.is_boundary)


def poly_normal(cos):
    n = Vector()
    for i, a in enumerate(cos):
        b = cos[(i + 1) % len(cos)]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n.normalized() if n.length > 1e-12 else n


# --- face filling ------------------------------------------------------------

def order_by_normal(verts, normal):
    """Sort verts counter-clockwise around `normal` so the face points along it."""
    c = sum((v.co for v in verts), Vector()) / len(verts)
    n = normal.normalized()
    u = verts[0].co - c
    u -= n * u.dot(n)
    if u.length < 1e-12:
        return list(verts)
    u.normalize()
    w = n.cross(u)
    return sorted(verts, key=lambda v: math.atan2((v.co - c).dot(w), (v.co - c).dot(u)))


def fix_winding(bm, verts):
    """Reverse `verts` if that agrees better with the winding of adjacent faces."""
    keep = rev = 0
    n = len(verts)
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        e = bm.edges.get((a, b))
        if e is None:
            continue
        for f in e.link_faces:
            for l in f.loops:
                if l.edge == e:
                    if l.vert == a:
                        rev += 1
                    else:
                        keep += 1
    return list(reversed(verts)) if rev > keep else list(verts)


def orient(verts, normal):
    """Reverse `verts` if their polygon faces away from `normal`."""
    if poly_normal([v.co for v in verts]).dot(normal) < 0:
        return list(reversed(verts))
    return list(verts)


def border_winding(edge):
    """(x, y) such that the existing face on `edge` runs x->y (new faces must run y->x)."""
    x, y = edge.verts
    if edge.link_faces:
        l = next(l for l in edge.link_faces[0].loops if l.edge == edge)
        x, y = l.vert, l.link_loop_next.vert
    return x, y


def order_from_edge(edge, picks):
    """Face verts for filling off a border edge with 1 or 2 picked verts."""
    x, y = border_winding(edge)
    if len(picks) == 1:
        return [y, x, picks[0]]
    p, q = picks
    if (x.co - p.co).length + (y.co - q.co).length > (x.co - q.co).length + (y.co - p.co).length:
        p, q = q, p
    return [y, x, p, q]


def can_make_face(bm, verts):
    if len(verts) < 3 or len(set(verts)) != len(verts):
        return False
    if bm.faces.get(verts) is not None:
        return False
    n = len(verts)
    for i in range(n):
        e = bm.edges.get((verts[i], verts[(i + 1) % n]))
        if e is not None and len(e.link_faces) >= 2:
            return False
    return True


def make_face(bm, verts):
    if not can_make_face(bm, verts):
        return None
    f = bm.faces.new(verts)
    f.normal_update()
    return f


# --- extend ------------------------------------------------------------------

def extend_edge(bm, edge, offset, project):
    """Pull a new quad off a border/wire edge. Returns (face, x, y, new_x, new_y)."""
    x, y = border_winding(edge)
    nx = bm.verts.new(project(x.co + offset))
    ny = bm.verts.new(project(y.co + offset))
    f = bm.faces.new([y, x, nx, ny])
    f.normal_update()
    return f, x, y, nx, ny


def weld(bm, targetmap):
    """Merge each key vert into its value vert."""
    targetmap = {a: b for a, b in targetmap.items() if a.is_valid and b.is_valid and a != b}
    if targetmap:
        bmesh.ops.weld_verts(bm, targetmap=targetmap)


# --- edge rings & loops --------------------------------------------------------

def edge_ring(edge, start):
    """Edges crossed by a loop cut through `edge`, as ordered (edge, side_vert) pairs.

    side_vert is the end of each ring edge on the same side as `start`.
    Returns (ring, closed).
    """
    faces = list(edge.link_faces)
    if not faces or len(faces) > 2:
        return [], False

    def walk(face):
        out = []
        e, s = edge, start
        seen = {edge}
        while face is not None and len(face.verts) == 4:
            l = next((l for l in face.loops if l.edge == e), None)
            if l is None:
                break
            o = l.link_loop_next.link_loop_next
            ns = o.link_loop_next.vert if l.vert == s else o.vert
            ne = o.edge
            if ne == edge:
                return out, True
            if ne in seen:
                break
            seen.add(ne)
            out.append((ne, ns))
            others = [f for f in ne.link_faces if f != face]
            face = others[0] if len(others) == 1 else None
            e, s = ne, ns
        return out, False

    fwd, closed = walk(faces[0])
    if closed:
        return [(edge, start)] + fwd, True
    back = walk(faces[1])[0] if len(faces) == 2 else []
    return list(reversed(back)) + [(edge, start)] + fwd, False


def insert_loop(bm, edge, start, t, project):
    """Cut a new edge loop across the quad ring through `edge` at factor t from `start`."""
    ring, _closed = edge_ring(edge, start)
    if len(ring) < 2:
        return []
    new = []
    for e, s in ring:
        target = s.co.lerp(e.other_vert(s).co, t)
        _ne, nv = bmesh.utils.edge_split(e, s, t)
        nv.co = project(target)
        new.append(nv)
    bmesh.ops.connect_verts(bm, verts=new)
    return new


def edge_loop(edge):
    """The edge loop running through an interior edge (stops at poles and borders)."""
    if len(edge.link_faces) != 2:
        return [edge]
    edges = [edge]
    seen = {edge}
    for l in edge.link_loops:
        while True:
            v = l.link_loop_next.vert
            if v.is_boundary or len(v.link_edges) != 4:
                break
            l = l.link_loop_next.link_loop_radial_next.link_loop_next
            e = l.edge
            if e in seen:
                break
            seen.add(e)
            edges.append(e)
    return edges


# --- delete / relax ----------------------------------------------------------

def delete_element(bm, kind, elem):
    if kind == 'VERT':
        bmesh.ops.delete(bm, geom=[elem], context='VERTS')
    elif kind == 'EDGE':
        if len(elem.link_faces) == 2:
            bmesh.ops.dissolve_edges(bm, edges=edge_loop(elem), use_verts=True, use_face_split=False)
        else:
            bmesh.ops.delete(bm, geom=[elem], context='EDGES')
    elif kind == 'FACE':
        bmesh.ops.delete(bm, geom=[elem], context='FACES')


def relax(weights, strength, project):
    """Laplacian smoothing of verts in `weights` ({vert: 0..1}); border verts slide along the border."""
    new = {}
    for v, w in weights.items():
        if not v.link_edges:
            continue
        if v.is_boundary or v.is_wire:
            nbrs = [e.other_vert(v) for e in v.link_edges if e.is_boundary or e.is_wire]
            if len(nbrs) != 2:
                continue
            a, b = nbrs[0].co - v.co, nbrs[1].co - v.co
            if a.length < 1e-12 or b.length < 1e-12 or a.angle(b) < CORNER_ANGLE:
                continue
        else:
            nbrs = [e.other_vert(v) for e in v.link_edges]
        avg = sum((n.co for n in nbrs), Vector()) / len(nbrs)
        new[v] = v.co.lerp(avg, min(1.0, w * strength))
    for v, co in new.items():
        v.co = project(co)
    return len(new)
