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
    bg.inputs['Strength'].default_value = 0.5

def card(loc, size, rot, strength, col=(1.0, 0.88, 0.7)):
    # 반사 전용 소프트박스: 카메라 시야 밖, 그림자는 만들지 않음
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc)
    o = bpy.context.object
    o.rotation_euler = rot
    m = bpy.data.materials.new('card')
    m.use_nodes = True
    n = m.node_tree.nodes
    n.clear()
    e = n.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = (*col, 1)
    e.inputs['Strength'].default_value = strength
    out = n.new('ShaderNodeOutputMaterial')
    m.node_tree.links.new(e.outputs[0], out.inputs[0])
    o.data.materials.append(m)
    o.visible_camera = False
    o.visible_shadow = False
    return o

def lights():
    sv = Vector((-0.55, 0.55, 0.63)).normalized()
    sun = bpy.data.lights.new('sun', 'SUN')
    sun.energy = 3.0
    sun.angle = math.radians(9)
    sun.color = (1.0, 0.9, 0.75)
    o = bpy.data.objects.new('sun', sun)
    bpy.context.collection.objects.link(o)
    o.rotation_euler = (-sv).to_track_quat('-Z', 'Y').to_euler()
    card((-900, 500, 260), 900, (math.radians(-35), math.radians(-50), 0), 14)
    card((900, -300, 200), 700, (math.radians(30), math.radians(55), 0), 7, (1.0, 0.8, 0.6))
    card((0, 700, 300), 800, (math.radians(-60), 0, 0), 5, (1.0, 0.95, 0.85))

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

def sph(r, loc, sc, m, parts):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc, segments=48, ring_count=24)
    o = bpy.context.object
    o.scale = sc
    bpy.ops.object.shade_smooth()
    return link(o, parts, m)

def tor(R, r, loc, m, parts):
    bpy.ops.mesh.primitive_torus_add(major_radius=R, minor_radius=r, location=loc, major_segments=64, minor_segments=16)
    o = bpy.context.object
    bpy.ops.object.shade_smooth()
    return link(o, parts, m)

def bow_bell(parts, x, y, gold):
    # 리본 매듭(빨강+초록)과 금색 종. 위치는 (x, y) 인자로 옮길 수 있음
    red = mat('ribred', (0.55, 0.02, 0.03), 0.0, 0.55, 0.0)
    grn = mat('ribgrn', (0.03, 0.30, 0.10), 0.0, 0.55, 0.0)
    z = 70
    for ang, m, dx in [(35, red, -17), (-35, grn, 17)]:
        o = sph(14, (x + dx, y + 6, z), (1.7, 0.75, 0.4), m, parts)
        o.rotation_euler = (0, 0, math.radians(ang))
    for ang, m, dx in [(-20, red, -8), (20, grn, 9)]:
        box((9, 38, 3), (x + dx, y - 22, z - 4), math.radians(ang), m, parts, 1)
    sph(8, (x, y + 4, z + 2), (1, 1, 0.7), red, parts)
    # 종
    bx, by = x + 18, y - 34
    sph(17, (bx, by, 48), (1, 1, 0.95), gold, parts)
    tor(15, 3.2, (bx, by, 36), gold, parts)
    tor(5, 1.8, (bx, by, 64), gold, parts)
    box((3, 15, 3), (bx, by - 10, 62), 0, mat('slit', (0.05, 0.03, 0.01), 0, 0.5), parts, 0.5)

def tonearm(parts):
    gold = mat('gold', (0.80, 0.52, 0.15), 1.0, 0.18)
    brass = mat('brass', (0.30, 0.18, 0.06), 1.0, 0.3)
    pts = [(0, 0), (40, -150), (76, -336), (66, -500), (43, -662), (-10, -725), (-65, -749)]
    cu = bpy.data.curves.new('arm', 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('BEZIER')
    sp.bezier_points.add(len(pts) - 1)
    for i, (x, y) in enumerate(pts):
        bp = sp.bezier_points[i]
        bp.co = (x, y, 45)
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    cu.bevel_depth = 15
    cu.bevel_resolution = 12
    cu.use_fill_caps = True
    arm = bpy.data.objects.new('arm', cu)
    bpy.context.collection.objects.link(arm)
    link(arm, parts, gold)
    cyl(30, 44, (0, 0, 34), gold, parts, 4)
    cyl(19, 10, (0, 0, 60), gold, parts, 3)
    tor(26, 3, (0, 0, 16), brass, parts)
    d = Vector((-0.57, -0.82)).normalized()
    ex, ey = pts[-1]
    rz = math.atan2(d.y, d.x) - math.pi / 2
    box((50, 100, 10), (ex + d.x * 38, ey + d.y * 38, 45), rz, gold, parts, 5)
    box((32, 44, 16), (ex + d.x * 64, ey + d.y * 64, 32), rz, brass, parts, 4)
    side = Vector((-d.y, d.x))
    box((5, 50, 5), (ex + d.x * 22 + side.x * 30, ey + d.y * 22 + side.y * 30, 46), rz + 0.5, gold, parts, 2)
    bow_bell(parts, 62, -600, gold)

def knobs(parts):
    gold = mat('gold', (0.80, 0.52, 0.15), 1.0, 0.15)
    red = mat('red', (0.55, 0.02, 0.03), 0.0, 0.12, 1.0)
    green = mat('green', (0.03, 0.30, 0.10), 0.0, 0.12, 1.0)
    brass = mat('brass', (0.30, 0.18, 0.06), 1.0, 0.3)
    dkred = mat('dkred', (0.25, 0.01, 0.02), 0.0, 0.35)
    dkgrn = mat('dkgrn', (0.01, 0.12, 0.04), 0.0, 0.35)
    spec = [(dkred, red), (dkgrn, green), (dkred, gold)]
    for i, (body, cap) in enumerate(spec):
        x = i * 200
        cyl(54, 8, (x, 0, 4), brass, parts, 2)
        tor(50, 5, (x, 0, 11), gold, parts)
        cyl(42, 26, (x, 0, 22), body, parts, 6)
        for k in range(48):
            a = 2 * math.pi * k / 48
            box((3.5, 5, 22), (x + 42 * math.cos(a), 42 * math.sin(a), 22), a + math.pi / 2, body, parts, 0.8)
        sph(34, (x, 0, 33), (1, 1, 0.42), cap, parts)
        # 눈금 점 (270도 호)
        for k in range(11):
            a = math.radians(225 - k * 27)
            sph(2.6, (x + 70 * math.cos(a), 70 * math.sin(a), 3), (1, 1, 1), gold, parts)
        # 지시선
        ti = math.radians(60)
        box((4, 24, 3), (x + 14 * math.cos(ti), 14 * math.sin(ti), 46), ti - math.pi / 2, gold if cap is not gold else red, parts, 1)

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
    run_job('knobs', knobs, 200, 0, 600, 200, a)
    print('done')
