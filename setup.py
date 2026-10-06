"""Scene settings, setup operators and the sidebar panel."""

import bpy


def _is_mesh(_self, obj):
    return obj.type == 'MESH'


class QuadDrawSettings(bpy.types.PropertyGroup):
    live_object: bpy.props.PointerProperty(
        name="Live Surface", type=bpy.types.Object, poll=_is_mesh,
        description="High-resolution mesh that new topology snaps to")
    brush_radius: bpy.props.IntProperty(
        name="Brush Radius", default=60, min=5, max=1000, subtype='PIXEL',
        description="Relax brush radius (press F in Quad Draw to resize)")
    relax_strength: bpy.props.FloatProperty(
        name="Relax Strength", default=0.5, min=0.01, max=1.0, subtype='FACTOR')


class QUADDRAW_OT_set_live(bpy.types.Operator):
    """Use the active mesh object as the live surface for Quad Draw"""
    bl_idname = "quad_draw.set_live"
    bl_label = "Set Live Surface"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and context.mode == 'OBJECT'

    def execute(self, context):
        context.scene.quad_draw.live_object = context.active_object
        self.report({'INFO'}, f"Live surface: {context.active_object.name}")
        return {'FINISHED'}


class QUADDRAW_OT_new_retopo(bpy.types.Operator):
    """Create an empty retopology mesh, enter Edit Mode and start Quad Draw"""
    bl_idname = "quad_draw.new_retopo"
    bl_label = "New Retopo Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def execute(self, context):
        live = context.scene.quad_draw.live_object
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        name = f"{live.name}_retopo" if live else "Retopo"
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        coll = live.users_collection[0] if live and live.users_collection else context.collection
        coll.objects.link(obj)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        overlay = context.space_data.overlay
        if hasattr(overlay, "show_retopology"):
            overlay.show_retopology = True
        bpy.ops.mesh.quad_draw('INVOKE_DEFAULT')
        return {'FINISHED'}


class VIEW3D_PT_quad_draw(bpy.types.Panel):
    bl_label = "Quad Draw"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quad Draw"

    def draw(self, context):
        s = context.scene.quad_draw
        layout = self.layout
        col = layout.column(align=True)
        col.prop(s, "live_object", text="")
        col.operator("quad_draw.set_live", icon='EYEDROPPER')
        layout.separator()
        col = layout.column(align=True)
        col.operator("quad_draw.new_retopo", icon='ADD')
        row = col.row()
        row.scale_y = 1.4
        row.operator("mesh.quad_draw", icon='MESH_GRID')
        layout.separator()
        col = layout.column(align=True)
        col.prop(s, "brush_radius")
        col.prop(s, "relax_strength")

        box = layout.box()
        box.label(text="Controls", icon='MOUSE_LMB')
        for line in (
            "LMB: place dot / drag to tweak",
            "Shift+LMB: fill quad",
            "Shift+drag: relax",
            "Tab+drag border edge: extend",
            "Ctrl+LMB: insert edge loop",
            "Ctrl+Shift+LMB: delete",
            "F: brush size",
            "Ctrl/Cmd+Z: undo · Esc: finish",
        ):
            box.label(text=line)


classes = (QuadDrawSettings, QUADDRAW_OT_set_live, QUADDRAW_OT_new_retopo, VIEW3D_PT_quad_draw)
