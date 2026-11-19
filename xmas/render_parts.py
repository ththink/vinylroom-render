# 크리스마스 턴테이블 3D 부품 렌더 (톤암·노브). 위에서 본 직교 카메라, 1BU = 1px
# 빛: 왼쪽 위 → 그림자는 오른쪽 아래 (앱 LightConfig 방향과 동일)
import bpy, sys, math, argparse, os
from mathutils import Vector

def get_args():
    a = sys.argv
    a = a[a.index('--') + 1:] if '--' in a else []
    p = argparse.ArgumentParser()
    p.add_argument('--outdir', default='render')
    p.add_argument('--samples', type=int, default=96)
    p.add_argument('--scale', type=int, default=2)
    return p.parse_args(a)

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.render.engine = 'CYCLES'
    s.cycles.device = 'CPU'
    s.cycles.use_denoising = True
    s.render.film_transparent = True
    s.view_settings.view_transform = 'Standard'
    s.render.image_settings.file_format = 'PNG'
    s.render.image_settings.color_mode = 'RGBA'
    return s

def mat(name, col, metal=0.0, rough=0.3, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*col, 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    if coat:
        b.inputs['Coat Weight'].default_value = coat
        b.inputs['Coat Roughness'].default_value = 0.08
    return m

def world(s):
    w = bpy.data.worlds.new('w')
    s.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (1.0, 0.82, 0.6, 1)
    bg.inputs['Strength'].default_value = 0.6

def lights():
    # 해: 왼쪽 위에서 비스듬히
    sv = Vector((-0.55, 0.55, 0.63)).normalized()
    sun = bpy.data.lights.new('sun', 'SUN')
    sun.energy = 3.2
    sun.angle = math.radians(4)
    sun.color = (1.0, 0.9, 0.75)
    o = bpy.data.objects.new('sun', sun)
    bpy.context.collection.objects.link(o)
    o.rotation_euler = (-sv).to_track_quat('-Z', 'Y').to_euler()
    # 반사용 부드러운 보조광(오른쪽 아래)
    ar = bpy.data.lights.new('fill', 'AREA')
    ar.energy = 60000
    ar.size = 600
    ar.color = (1.0, 0.8, 0.6)
    o2 = bpy.data.objects.new('fill', ar)
    bpy.context.collection.objects.link(o2)
    o2.location = (500, -300, 500)
    o2.rotation_euler = (math.radians(30), math.radians(40), 0)

def camera(s, cx, cy, w, h, scale):
    c = bpy.data.cameras.new('cam')
    c.type = 'ORTHO'
    c.ortho_scale = max(w, h)
    o = bpy.data.objects.new('cam', c)
    bpy.context.collection.objects.link(o)
    o.location = (cx, cy, 600)
    s.camera = o
    s.render.resolution_x = w
    s.render.resolution_y = h
    s.render.resolution_percentage = scale * 100

def catcher(cx, cy):
    bpy.ops.mesh.primitive_plane_add(size=3000, location=(cx, cy, 0))
    p = bpy.context.object
    p.is_shadow_catcher = True
    return p

def link(o, parts, m=None):
    if m:
        o.data.materials.append(m)
    parts.append(o)
    return o

def cyl(r, d, loc, m, parts, bevel=0.0):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=d, location=loc, vertices=64)
    o = bpy.context.object
    bpy.ops.object.shade_smooth()
    if bevel:
        b = o.modifiers.new('b', 'BEVEL')
        b.width = bevel
        b.segments = 4
    return link(o, parts, m)

def box(size, loc, rotz, m, parts, bevel=1.5):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.object
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    o.rotation_euler = (0, 0, rotz)
    bpy.ops.object.transform_apply(scale=True)
    b = o.modifiers.new('b', 'BEVEL')
    b.width = bevel
    b.segments = 3
    return link(o, parts, m)

def tonearm(parts):
    gold = mat('gold', (0.85, 0.62, 0.22), 1.0, 0.22)
    dark = mat('dark', (0.04, 0.04, 0.045), 0.0, 0.4)
    pts = [(0, 0), (40, -150), (76, -336), (66, -500), (43, -662), (-10, -725), (-65, -749)]
    cu = bpy.data.curves.new('arm', 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(len(pts) - 1)
    for i, (x, y) in enumerate(pts):
        bp = sp.bezier_points[i]
        bp.co = (x, y, 45)
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    cu.bevel_depth = 11
    cu.bevel_resolution = 8
    cu.use_fill_caps = True
    arm = bpy.data.objects.new('arm', cu)
    bpy.context.collection.objects.link(arm)
    link(arm, parts, gold)
    # 피벗 칼라
    cyl(26, 40, (0, 0, 32), gold, parts, 3)
    cyl(15, 8, (0, 0, 54), gold, parts, 2)
    # 헤드셸
    d = Vector((-0.57, -0.82)).normalized()
    ex, ey = pts[-1]
    rz = math.atan2(d.y, d.x) - math.pi / 2
    box((44, 96, 8), (ex + d.x * 38, ey + d.y * 38, 45), rz, gold, parts, 2)
    box((30, 42, 14), (ex + d.x * 62, ey + d.y * 62, 33), rz, dark, parts, 2)
    # 핑거 리프트(헤드셸 옆 얇은 막대)
    side = Vector((-d.y, d.x))
    box((4, 46, 4), (ex + d.x * 20 + side.x * 28, ey + d.y * 20 + side.y * 28, 45), rz + 0.5, gold, parts, 1)

def knobs(parts):
    gold = mat('gold', (0.85, 0.62, 0.22), 1.0, 0.22)
    red = mat('red', (0.55, 0.02, 0.03), 0.0, 0.25, 0.8)
    green = mat('green', (0.03, 0.30, 0.10), 0.0, 0.25, 0.8)
    ring = mat('ring', (0.35, 0.25, 0.1), 1.0, 0.4)
    spec = [(red, red), (green, green), (red, gold)]
    for i, (body, cap) in enumerate(spec):
        x = i * 140
        cyl(52, 10, (x, 0, 5), ring, parts, 2)
        cyl(44, 34, (x, 0, 25), body, parts, 6)
        cyl(30, 6, (x, 0, 44), cap, parts, 2)
        box((4, 26, 3), (x, 14, 48), 0.35, gold if cap is not gold else red, parts, 1)

def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

def run_job(name, builder, cx, cy, w, h, a):
    s = reset()
    world(s)
    lights()
    camera(s, cx, cy, w, h, a.scale)
    parts = []
    builder(parts)
    cp = catcher(cx, cy)
    s.cycles.samples = a.samples
    os.makedirs(a.outdir, exist_ok=True)
    # 1) 색 (그림자 받침판은 숨김)
    cp.hide_render = True
    s.render.filepath = os.path.join(a.outdir, name + '_color.png')
    bpy.ops.render.render(write_still=True)
    # 2) 그림자만
    cp.hide_render = False
    for o in parts:
        o.is_holdout = True
    s.render.filepath = os.path.join(a.outdir, name + '_shadow.png')
    bpy.ops.render.render(write_still=True)

if __name__ == '__main__':
    a = get_args()
    run_job('tonearm', tonearm, 0, -380, 600, 1000, a)
    run_job('knobs', knobs, 140, 0, 420, 140, a)
    print('done')
