"""Quad Draw: a Maya-style retopology tool for Blender."""

import bpy

from . import operator, prefs, setup

_classes = (prefs.QuadDrawPreferences, *setup.classes, operator.MESH_OT_quad_draw)
_keymaps = []


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.quad_draw = bpy.props.PointerProperty(type=setup.QuadDrawSettings)

    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="Mesh", space_type='EMPTY')
        kmi = km.keymap_items.new(operator.MESH_OT_quad_draw.bl_idname, 'Q', 'PRESS', shift=True)
        _keymaps.append((km, kmi))


def unregister():
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    del bpy.types.Scene.quad_draw
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
