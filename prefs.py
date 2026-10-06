import bpy
from types import SimpleNamespace

_DEFAULTS = dict(pick_radius=14, fill_radius=140, drag_threshold=4, auto_weld=True)


class QuadDrawPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    pick_radius: bpy.props.IntProperty(
        name="Pick Radius", description="Screen distance (px) for hovering vertices and edges",
        default=_DEFAULTS["pick_radius"], min=3, max=100, subtype='PIXEL')
    fill_radius: bpy.props.IntProperty(
        name="Fill Search Radius", description="Screen distance (px) searched for verts when previewing a quad fill",
        default=_DEFAULTS["fill_radius"], min=20, max=1000, subtype='PIXEL')
    drag_threshold: bpy.props.IntProperty(
        name="Drag Threshold", description="Mouse movement (px) before a click becomes a drag",
        default=_DEFAULTS["drag_threshold"], min=1, max=50, subtype='PIXEL')
    auto_weld: bpy.props.BoolProperty(
        name="Auto Weld", description="Merge a dragged vertex into another vertex when released on top of it",
        default=_DEFAULTS["auto_weld"])

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "pick_radius")
        col.prop(self, "fill_radius")
        col.prop(self, "drag_threshold")
        col.prop(self, "auto_weld")


def get_prefs(context):
    addon = context.preferences.addons.get(__package__)
    if addon is not None and addon.preferences is not None:
        return addon.preferences
    return SimpleNamespace(**_DEFAULTS)
