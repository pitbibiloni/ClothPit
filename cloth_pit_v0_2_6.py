bl_info = {
    "name": "ClothPit",
    "author": "pit_",
    "version": (0, 2, 6),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > ClothPit",
    "description": "Generate cloth meshes, configure pinning, collisions, modifiers and wind",
    "category": "Object",
}

import bpy
import bmesh
from bpy.props import (
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


PIN_GROUP_NAME = "Cloth_Pin"

# Runtime-only storage for restoring the source mesh after Freeze.
_FROZEN_MESH_STATE = {}


def update_selected_wind(props, context):
    """Apply wind controls to the active selected wind object, if any."""
    obj = context.object if context else None
    if obj is None or getattr(obj, "field", None) is None:
        return
    field = obj.field
    if getattr(field, "type", None) != 'WIND':
        return
    field.strength = props.wind_strength
    if hasattr(field, "flow"):
        field.flow = props.wind_flow
    if hasattr(field, "noise"):
        field.noise = props.wind_noise


def active_mesh(context):
    obj = context.object
    return obj if obj and obj.type == 'MESH' else None

def ensure_pin_group(obj):
    group = obj.vertex_groups.get(PIN_GROUP_NAME)
    if group is None:
        group = obj.vertex_groups.new(name=PIN_GROUP_NAME)
    return group


def set_if_supported(settings, name, value):
    if hasattr(settings, name):
        try:
            setattr(settings, name, value)
        except (TypeError, ValueError, AttributeError):
            pass


def apply_cloth_preset(obj, preset):
    cloth_mod = next((m for m in obj.modifiers if m.type == 'CLOTH'), None)
    if cloth_mod is None:
        cloth_mod = obj.modifiers.new("Cloth Simulation", 'CLOTH')

    settings = cloth_mod.settings
    # Approximate starting profiles, intended as practical presets rather than
    # physically exact material measurements.
    profiles = {
        'FABRIC': {
            "mass": 0.3, "tension_stiffness": 15.0,
            "compression_stiffness": 15.0, "shear_stiffness": 5.0,
            "bending_stiffness": 0.5, "air_damping": 1.0,
        },
        'COTTON': {
            "mass": 0.25, "tension_stiffness": 10.0,
            "compression_stiffness": 10.0, "shear_stiffness": 4.0,
            "bending_stiffness": 0.25, "air_damping": 1.0,
        },
        'LEATHER': {
            "mass": 0.8, "tension_stiffness": 35.0,
            "compression_stiffness": 35.0, "shear_stiffness": 15.0,
            "bending_stiffness": 5.0, "air_damping": 1.0,
        },
        'CANVAS': {
            "mass": 0.6, "tension_stiffness": 30.0,
            "compression_stiffness": 30.0, "shear_stiffness": 12.0,
            "bending_stiffness": 3.0, "air_damping": 1.0,
        },
        'CARPET': {
            "mass": 1.5, "tension_stiffness": 40.0,
            "compression_stiffness": 40.0, "shear_stiffness": 20.0,
            "bending_stiffness": 8.0, "air_damping": 2.0,
        },
    }
    for prop, value in profiles[preset].items():
        set_if_supported(settings, prop, value)

    # The dedicated vertex group is used as the cloth pinning group.
    if obj.vertex_groups.get(PIN_GROUP_NAME):
        settings.vertex_group_mass = PIN_GROUP_NAME
    return cloth_mod



class CLOTHPIT_Properties(bpy.types.PropertyGroup):
    width: FloatProperty(name="Width", default=2.0, min=0.01, unit='LENGTH')
    height: FloatProperty(name="Height", default=1.0, min=0.01, unit='LENGTH')
    ratio: EnumProperty(
        name="Aspect Ratio",
        items=[
            ('CUSTOM', "Custom", "Use Width and Height"),
            ('1x1', "1 x 1", "Square"),
            ('1x2', "1 x 2", "Portrait ratio"),
            ('2x1', "2 x 1", "Landscape ratio"),
            ('2x2', "2 x 2", "Square, 2-unit ratio"),
            ('1x3', "1 x 3", "Tall or wide, based on orientation"),
            ('3x1', "3 x 1", "Wide"),
        ],
        default='1x2',
    )
    subdivisions_x: IntProperty(name="Subdivisions X", default=40, min=1, max=500)
    subdivisions_y: IntProperty(name="Subdivisions Y", default=20, min=1, max=500)
    cloth_preset: EnumProperty(
        name="Fabric Preset",
        items=[
            ('FABRIC', "Fabric", "General-purpose fabric"),
            ('COTTON', "Cotton", "Soft, flexible starting profile"),
            ('LEATHER', "Leather", "Heavier, stiffer starting profile"),
            ('CANVAS', "Canvas", "Heavy-duty fabric starting profile"),
            ('CARPET', "Carpet", "Heavy and resistant starting profile"),
        ],
        default='FABRIC',
    )
    collision_distance: FloatProperty(name="Distance", default=0.015, min=0.0, max=1.0)
    collision_friction: FloatProperty(name="Friction", default=5.0, min=0.0, max=80.0)
    self_collision_distance: FloatProperty(name="Self Collision Distance", default=0.01, min=0.0, max=1.0)
    self_collision_friction: FloatProperty(name="Self Collision Friction", default=5.0, min=0.0, max=80.0)
    wind_strength: FloatProperty(name="Strength", default=1000.0, min=0.0, max=100000.0, update=update_selected_wind)
    wind_flow: FloatProperty(name="Flow", default=1.0, min=0.0, max=10.0, update=update_selected_wind)
    wind_noise: FloatProperty(name="Noise", default=0.1, min=0.0, max=10.0, update=update_selected_wind)
    solidify_thickness: FloatProperty(name="Thickness", default=0.01, min=-10.0, max=10.0, unit='LENGTH')
    subdivision_view: IntProperty(name="Viewport", default=1, min=0, max=6)
    subdivision_render: IntProperty(name="Render", default=2, min=0, max=6)


class CLOTHPIT_OT_generate_plane(bpy.types.Operator):
    bl_idname = "clothpit.generate_plane"
    bl_label = "Generate Cloth Mesh"
    bl_description = "Create a uniformly subdivided quad mesh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.clothpit_props
        width, height = props.width, props.height

        if props.ratio != 'CUSTOM':
            a, b = props.ratio.split('x')
            ratio = float(a) / float(b)
            # Keep the current area scale approximately stable while changing ratio.
            area = max(width * height, 0.0001)
            width = (area * ratio) ** 0.5
            height = (area / ratio) ** 0.5
            props.width = width
            props.height = height

        nx, ny = props.subdivisions_x, props.subdivisions_y
        verts = []
        faces = []
        for j in range(ny + 1):
            y = (j / ny - 0.5) * height
            for i in range(nx + 1):
                x = (i / nx - 0.5) * width
                verts.append((x, y, 0.0))

        row = nx + 1
        for j in range(ny):
            for i in range(nx):
                v = j * row + i
                faces.append((v, v + 1, v + row + 1, v + row))

        mesh = bpy.data.meshes.new("ClothMesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        # Automatic square UV unwrap: the full mesh spans the 0-1 UV square.
        uv_layer = mesh.uv_layers.new(name="ClothUV")
        for poly in mesh.polygons:
            for loop_index in poly.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                vx, vy, _vz = mesh.vertices[vertex_index].co
                uv_layer.data[loop_index].uv = ((vx / width) + 0.5, (vy / height) + 0.5)
        obj = bpy.data.objects.new("Cloth", mesh)
        context.collection.objects.link(obj)
        context.view_layer.objects.active = obj
        obj.select_set(True)
        for other in context.selected_objects:
            if other != obj:
                other.select_set(False)

        ensure_pin_group(obj)
        obj["cloth_pit"] = True
        # Add the base Cloth modifier immediately; Apply Preset can change its profile later.
        apply_cloth_preset(obj, 'FABRIC')
        self.report({'INFO'}, f"Created cloth mesh with base Cloth simulation ({nx} x {ny} quads)")
        return {'FINISHED'}


class CLOTHPIT_OT_apply_preset(bpy.types.Operator):
    bl_idname = "clothpit.apply_preset"
    bl_label = "Apply Preset"
    bl_description = "Apply the selected fabric profile to the active mesh's Cloth modifier"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Select a cloth mesh")
            return {'CANCELLED'}
        props = context.scene.clothpit_props
        apply_cloth_preset(obj, props.cloth_preset)
        self.report({'INFO'}, f"Applied preset: {props.cloth_preset.title()}")
        return {'FINISHED'}


class CLOTHPIT_OT_pin_selected(bpy.types.Operator):
    bl_idname = "clothpit.pin_selected"
    bl_label = "Pin Selected"
    bl_description = "Assign selected vertices to the cloth pin group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None or obj.mode != 'EDIT':
            self.report({'ERROR'}, "Enter Edit Mode and select vertices first")
            return {'CANCELLED'}
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        indices = [v.index for v in bm.verts if v.select]
        if not indices:
            self.report({'WARNING'}, "No vertices selected")
            return {'CANCELLED'}

        # VertexGroup.add() cannot run in Edit Mode. Store the selection, switch
        # to Object Mode for the assignment, then return to Edit Mode.
        bpy.ops.object.mode_set(mode='OBJECT')
        group = ensure_pin_group(obj)
        group.add(indices, 1.0, 'REPLACE')
        cloth_mod = next((m for m in obj.modifiers if m.type == 'CLOTH'), None)
        if cloth_mod:
            set_if_supported(cloth_mod.settings, "vertex_group_mass", group.name)
        bpy.ops.object.mode_set(mode='EDIT')
        self.report({'INFO'}, f"Pinned {len(indices)} vertices")
        return {'FINISHED'}


class CLOTHPIT_OT_select_pinned(bpy.types.Operator):
    bl_idname = "clothpit.select_pinned"
    bl_label = "Select Pinned"
    bl_description = "Select vertices belonging to the pin group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Select a cloth mesh")
            return {'CANCELLED'}
        group = obj.vertex_groups.get(PIN_GROUP_NAME)
        if group is None:
            self.report({'WARNING'}, "No pin group found")
            return {'CANCELLED'}
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for v in obj.data.vertices:
            v.select = False
        try:
            group_index = group.index
            for v in obj.data.vertices:
                for assignment in v.groups:
                    if assignment.group == group_index and assignment.weight > 0.0:
                        v.select = True
                        break
        except Exception as exc:
            self.report({'ERROR'}, f"Could not select pinned vertices: {exc}")
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        return {'FINISHED'}


class CLOTHPIT_OT_unpin_selected(bpy.types.Operator):
    bl_idname = "clothpit.unpin_selected"
    bl_label = "Unpin Selected"
    bl_description = "Remove selected vertices from the pin group"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None or obj.mode != 'EDIT':
            self.report({'ERROR'}, "Enter Edit Mode and select vertices first")
            return {'CANCELLED'}
        group = obj.vertex_groups.get(PIN_GROUP_NAME)
        if group is None:
            self.report({'WARNING'}, "No pin group found")
            return {'CANCELLED'}
        bm = bmesh.from_edit_mesh(obj.data)
        indices = [v.index for v in bm.verts if v.select]
        if not indices:
            self.report({'WARNING'}, "No vertices selected")
            return {'CANCELLED'}
        group.remove(indices)
        return {'FINISHED'}


class CLOTHPIT_OT_clear_pinning(bpy.types.Operator):
    bl_idname = "clothpit.clear_pinning"
    bl_label = "Clear All Pinning"
    bl_description = "Remove the pin group and release all vertices"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}
        group = obj.vertex_groups.get(PIN_GROUP_NAME)
        if group:
            obj.vertex_groups.remove(group)
        for mod in obj.modifiers:
            if mod.type == 'CLOTH' and hasattr(mod.settings, "vertex_group_mass"):
                mod.settings.vertex_group_mass = ""
        ensure_pin_group(obj)
        return {'FINISHED'}


class CLOTHPIT_OT_generate_collision(bpy.types.Operator):
    bl_idname = "clothpit.generate_collision"
    bl_label = "Generate Collision"
    bl_description = "Enable collision physics on selected mesh objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.clothpit_props
        objects = [o for o in context.selected_objects if o.type == 'MESH' and o != context.object]
        if not objects:
            # Allow a single selected collider too, but warn that it must not be the cloth.
            objects = [o for o in context.selected_objects if o.type == 'MESH']
        count = 0
        for obj in objects:
            try:
                if getattr(obj, "collision", None) is None:
                    with context.temp_override(object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
                        bpy.ops.object.modifier_add(type='COLLISION')
                collision = getattr(obj, "collision", None)
                if collision is not None:
                    if hasattr(collision, "thickness_outer"):
                        collision.thickness_outer = props.collision_distance
                    if hasattr(collision, "cloth_friction"):
                        collision.cloth_friction = props.collision_friction
                    count += 1
            except Exception:
                # Blender versions may expose collision setup differently.
                try:
                    with context.temp_override(object=obj, active_object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
                        bpy.ops.object.modifier_add(type='COLLISION')
                    collision = getattr(obj, "collision", None)
                    if collision is not None:
                        if hasattr(collision, "thickness_outer"):
                            collision.thickness_outer = props.collision_distance
                        if hasattr(collision, "cloth_friction"):
                            collision.cloth_friction = props.collision_friction
                        count += 1
                except Exception:
                    pass
        if count == 0:
            self.report({'ERROR'}, "Could not enable collisions. Select collider mesh objects and try again.")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Collision enabled on {count} object(s)")
        return {'FINISHED'}


class CLOTHPIT_OT_clear_collision(bpy.types.Operator):
    bl_idname = "clothpit.clear_collision"
    bl_label = "Clear Collision"
    bl_description = "Remove collision setup from selected objects where supported"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            removed = False
            for mod in list(obj.modifiers):
                if mod.type == 'COLLISION':
                    obj.modifiers.remove(mod)
                    removed = True
            if removed:
                count += 1
        self.report({'INFO'}, f"Removed collision setup from {count} object(s)")
        return {'FINISHED'}



class CLOTHPIT_OT_self_collision(bpy.types.Operator):
    bl_idname = "clothpit.self_collision"
    bl_label = "Enable Self Collision"
    bl_description = "Enable cloth self-collision on the selected cloth mesh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Select the cloth mesh")
            return {'CANCELLED'}

        cloth_mod = next((m for m in obj.modifiers if m.type == 'CLOTH'), None)
        if cloth_mod is None:
            self.report({'ERROR'}, "The selected mesh has no Cloth modifier. Generate cloth first.")
            return {'CANCELLED'}

        # In Blender, self-collision controls belong to ClothModifier.collision_settings,
        # not ClothModifier.settings.
        collision_settings = getattr(cloth_mod, "collision_settings", None)
        if collision_settings is None or not hasattr(collision_settings, "use_self_collision"):
            self.report({'ERROR'}, "Could not access Cloth self-collision settings.")
            return {'CANCELLED'}

        props = context.scene.clothpit_props
        collision_settings.use_self_collision = True
        set_if_supported(collision_settings, "self_friction", props.self_collision_friction)
        set_if_supported(collision_settings, "distance_min", props.self_collision_distance)

        self.report({'INFO'}, f"Self-collision enabled on {obj.name}")
        return {'FINISHED'}


class CLOTHPIT_OT_add_solidify(bpy.types.Operator):
    bl_idname = "clothpit.add_solidify"
    bl_label = "Add Solidify"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}
        mod = next((m for m in obj.modifiers if m.type == 'SOLIDIFY'), None)
        if mod is None:
            mod = obj.modifiers.new("Cloth Thickness", 'SOLIDIFY')
        mod.thickness = context.scene.clothpit_props.solidify_thickness
        return {'FINISHED'}


class CLOTHPIT_OT_add_subdivision(bpy.types.Operator):
    bl_idname = "clothpit.add_subdivision"
    bl_label = "Add Subdivision"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}
        props = context.scene.clothpit_props
        mod = next((m for m in obj.modifiers if m.type == 'SUBSURF'), None)
        if mod is None:
            mod = obj.modifiers.new("Cloth Smoothing", 'SUBSURF')
        mod.levels = props.subdivision_view
        mod.render_levels = props.subdivision_render
        return {'FINISHED'}


class CLOTHPIT_OT_add_wind(bpy.types.Operator):
    bl_idname = "clothpit.add_wind"
    bl_label = "Create Wind"
    bl_description = "Create a new wind force field at the 3D cursor using the current settings"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.clothpit_props
        location = context.scene.cursor.location.copy()
        bpy.ops.object.effector_add(type='WIND', location=location)
        wind = context.object
        wind.name = "Cloth Wind"
        field = wind.field
        if field:
            field.strength = props.wind_strength
            if hasattr(field, "flow"):
                field.flow = props.wind_flow
            if hasattr(field, "noise"):
                field.noise = props.wind_noise
        return {'FINISHED'}




def get_active_cloth_modifier(context):
    obj = active_mesh(context)
    if obj is None:
        return None, None
    mod = next((m for m in obj.modifiers if m.type == 'CLOTH'), None)
    return obj, mod


class CLOTHPIT_OT_timeline_play_pause(bpy.types.Operator):
    bl_idname = "clothpit.timeline_play_pause"
    bl_label = "Play / Pause"
    bl_description = "Use Blender's timeline playback toggle"

    def execute(self, context):
        try:
            bpy.ops.screen.animation_play()
        except RuntimeError as exc:
            self.report({'ERROR'}, f"Could not toggle playback: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class CLOTHPIT_OT_timeline_reset(bpy.types.Operator):
    bl_idname = "clothpit.timeline_reset"
    bl_label = "Reset to Start"
    bl_description = "Stop playback and return to the scene start frame"

    def execute(self, context):
        screen = context.screen
        if screen and screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        context.scene.frame_set(context.scene.frame_start)
        return {'FINISHED'}


class CLOTHPIT_OT_simulation_freeze(bpy.types.Operator):
    bl_idname = "clothpit.simulation_freeze"
    bl_label = "Freeze Simulation"
    bl_description = "Freeze the visible cloth shape at the current frame while the timeline continues"

    def execute(self, context):
        obj, mod = get_active_cloth_modifier(context)
        if mod is None:
            self.report({'ERROR'}, "Select a mesh with a Cloth modifier")
            return {'CANCELLED'}
        if obj.name in _FROZEN_MESH_STATE:
            self.report({'INFO'}, "Simulation is already frozen")
            return {'CANCELLED'}
        try:
            depsgraph = context.evaluated_depsgraph_get()
            evaluated_obj = obj.evaluated_get(depsgraph)
            frozen_mesh = bpy.data.meshes.new_from_object(
                evaluated_obj, preserve_all_data_layers=True, depsgraph=depsgraph
            )
            frozen_mesh.name = f"{obj.data.name}_FrozenFrame_{context.scene.frame_current}"
            _FROZEN_MESH_STATE[obj.name] = {
                "source_mesh": obj.data,
                "frozen_mesh": frozen_mesh,
                "modifier_name": mod.name,
                "show_viewport": mod.show_viewport,
            }
            obj.data = frozen_mesh
            mod.show_viewport = False
            obj["clothpit_simulation_frozen"] = True
        except Exception as exc:
            self.report({'ERROR'}, f"Could not freeze current frame: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Cloth frozen at frame {context.scene.frame_current}")
        return {'FINISHED'}


class CLOTHPIT_OT_simulation_unfreeze(bpy.types.Operator):
    bl_idname = "clothpit.simulation_unfreeze"
    bl_label = "Unfreeze Simulation"
    bl_description = "Restore the original mesh and resume Cloth evaluation"

    def execute(self, context):
        obj, mod = get_active_cloth_modifier(context)
        if mod is None:
            self.report({'ERROR'}, "Select a mesh with a Cloth modifier")
            return {'CANCELLED'}
        state = _FROZEN_MESH_STATE.pop(obj.name, None)
        if state is None:
            self.report({'ERROR'}, "No frozen pose is stored for this object")
            return {'CANCELLED'}
        frozen_mesh = state["frozen_mesh"]
        obj.data = state["source_mesh"]
        mod.show_viewport = state["show_viewport"]
        obj["clothpit_simulation_frozen"] = False
        if frozen_mesh.users == 0:
            bpy.data.meshes.remove(frozen_mesh)
        self.report({'INFO'}, "Cloth simulation resumed")
        return {'FINISHED'}


class CLOTHPIT_OT_simulation_bake(bpy.types.Operator):
    bl_idname = "clothpit.simulation_bake"
    bl_label = "Bake / Apply Cloth"
    bl_description = "Apply the Cloth modifier destructively at the current frame"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj, mod = get_active_cloth_modifier(context)
        if mod is None:
            self.report({'ERROR'}, "Select a mesh with a Cloth modifier")
            return {'CANCELLED'}
        if obj.name in _FROZEN_MESH_STATE or not mod.show_viewport:
            self.report({'ERROR'}, "Unfreeze the simulation before applying Cloth")
            return {'CANCELLED'}
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            with context.temp_override(
                object=obj, active_object=obj,
                selected_objects=[obj], selected_editable_objects=[obj]
            ):
                result = bpy.ops.object.modifier_apply(modifier=mod.name)
            if 'FINISHED' not in result:
                self.report({'ERROR'}, "Blender could not apply the Cloth modifier")
                return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Could not apply Cloth modifier: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Cloth modifier applied at frame {context.scene.frame_current}")
        return {'FINISHED'}


class CLOTHPIT_OT_simulation_free_bake(bpy.types.Operator):
    bl_idname = "clothpit.simulation_free_bake"
    bl_label = "Clear Bake"
    bl_description = "Free the cached Cloth simulation so it can be recalculated"

    def execute(self, context):
        obj, mod = get_active_cloth_modifier(context)
        if mod is None:
            self.report({'ERROR'}, "Select a mesh with a Cloth modifier")
            return {'CANCELLED'}
        try:
            with context.temp_override(scene=context.scene, object=obj, active_object=obj, point_cache=mod.point_cache):
                bpy.ops.ptcache.free_bake()
        except Exception as exc:
            self.report({'ERROR'}, f"Could not clear bake: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class CLOTHPIT_PT_main(bpy.types.Panel):
    bl_label = "ClothPit"
    bl_idname = "CLOTHPIT_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ClothPit"

    def draw(self, context):
        layout = self.layout
        props = context.scene.clothpit_props
        obj = active_mesh(context)

        # Generate Cloth is first: mesh creation also installs base Cloth physics.
        box = layout.box()
        box.label(text="1. Generate Cloth", icon='MESH_GRID')
        box.operator("clothpit.generate_plane", text="Generate Static Cloth Mesh", icon='MESH_GRID')
        col = box.column(align=True)
        col.prop(props, "ratio")
        row = col.row(align=True)
        row.prop(props, "width")
        row.prop(props, "height")
        row = col.row(align=True)
        row.prop(props, "subdivisions_x")
        row.prop(props, "subdivisions_y")
        box.separator()
        box.prop(props, "cloth_preset", text="Fabric Type")
        box.operator("clothpit.apply_preset", text="Apply Preset", icon='MOD_CLOTH')

        box = layout.box()
        box.label(text="2. Pinning Tools", icon='PINNED')
        box.label(text="Pin/Unpin require Edit Mode vertex selection")
        col = box.column(align=True)
        col.operator("clothpit.pin_selected", icon='PINNED')
        col.operator("clothpit.select_pinned", icon='RESTRICT_SELECT_OFF')
        col.operator("clothpit.unpin_selected", icon='UNPINNED')
        col.operator("clothpit.clear_pinning", icon='X')

        box = layout.box()
        box.label(text="3. Collision Tools", icon='MOD_PHYSICS')
        box.prop(props, "collision_distance")
        box.prop(props, "collision_friction")
        box.operator("clothpit.generate_collision", icon='MOD_PHYSICS')
        box.prop(props, "self_collision_distance")
        box.prop(props, "self_collision_friction")
        box.operator("clothpit.self_collision", text="Enable Self Collision", icon='MOD_PHYSICS')
        box.operator("clothpit.clear_collision", icon='TRASH')

        box = layout.box()
        box.label(text="4. Modifiers", icon='MODIFIER')
        box.prop(props, "solidify_thickness")
        box.operator("clothpit.add_solidify", icon='MOD_SOLIDIFY')
        row = box.row(align=True)
        row.prop(props, "subdivision_view")
        row.prop(props, "subdivision_render")
        box.operator("clothpit.add_subdivision", icon='MOD_SUBSURF')

        box = layout.box()
        box.label(text="5. Simulation", icon='TIME')
        row = box.row(align=True)
        row.prop(context.scene, "frame_start", text="Start")
        row.prop(context.scene, "frame_end", text="End")
        row = box.row(align=True)
        row.operator("clothpit.timeline_play_pause", text="Play / Pause", icon='PLAY')
        row.operator("clothpit.timeline_reset", text="Reset", icon='FILE_REFRESH')
        row = box.row(align=True)
        row.operator("clothpit.simulation_freeze", text="Freeze", icon='PAUSE')
        row.operator("clothpit.simulation_unfreeze", text="Unfreeze", icon='PLAY')
        row.operator("clothpit.simulation_bake", text="Bake / Apply", icon='CHECKMARK')
        box.operator("clothpit.simulation_free_bake", text="Clear Bake", icon='TRASH')
        active_cloth = next((m for m in obj.modifiers if m.type == 'CLOTH'), None) if obj else None
        if active_cloth:
            if active_cloth.point_cache.is_baked:
                box.label(text="Simulation cache: Baked", icon='CHECKMARK')
            elif not active_cloth.show_viewport:
                box.label(text="Simulation frozen at stored pose", icon='PAUSE')
            else:
                box.label(text="Simulation cache: Live", icon='PLAY')
        else:
            box.label(text="Select a cloth mesh to control its simulation", icon='INFO')

        # Wind Generator is intentionally the last section. Settings update the
        # selected Wind live; Create Wind makes a new field with these values.
        box = layout.box()
        box.label(text="6. Wind Generator", icon='FORCE_WIND')
        active = context.object
        is_wind = bool(active and getattr(active, "field", None) and active.field.type == 'WIND')
        if is_wind:
            box.label(text="Editing selected Wind", icon='CHECKMARK')
        else:
            box.label(text="Select a Wind to edit, or set values for a new one", icon='INFO')
        box.prop(props, "wind_strength")
        box.prop(props, "wind_flow")
        box.prop(props, "wind_noise")
        box.operator("clothpit.add_wind", text="Create Wind", icon='FORCE_WIND')



CLASSES = (
    CLOTHPIT_Properties,
    CLOTHPIT_OT_generate_plane,
    CLOTHPIT_OT_apply_preset,
    CLOTHPIT_OT_pin_selected,
    CLOTHPIT_OT_select_pinned,
    CLOTHPIT_OT_unpin_selected,
    CLOTHPIT_OT_clear_pinning,
    CLOTHPIT_OT_generate_collision,
    CLOTHPIT_OT_self_collision,
    CLOTHPIT_OT_clear_collision,
    CLOTHPIT_OT_add_solidify,
    CLOTHPIT_OT_add_subdivision,
    CLOTHPIT_OT_add_wind,
    CLOTHPIT_OT_timeline_play_pause,
    CLOTHPIT_OT_timeline_reset,
    CLOTHPIT_OT_simulation_freeze,
    CLOTHPIT_OT_simulation_unfreeze,
    CLOTHPIT_OT_simulation_bake,
    CLOTHPIT_OT_simulation_free_bake,
    CLOTHPIT_PT_main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.clothpit_props = PointerProperty(type=CLOTHPIT_Properties)


def unregister():
    if hasattr(bpy.types.Scene, "clothpit_props"):
        del bpy.types.Scene.clothpit_props
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
