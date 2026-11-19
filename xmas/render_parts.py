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

def turned_metal(name, col, rough=0.3):
    # 터닝 가공 금속: 비등방성 + 반경 접선 → 가운데서 퍼지는 부채꼴 하이라이트
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*col, 1)
    b.inputs['Metallic'].default_value = 1.0
    b.inputs['Roughness'].default_value = rough
    b.inputs['Anisotropic'].default_value = 0.95
    tg = nt.nodes.new('ShaderNodeTangent')
    tg.direction_type = 'RADIAL'
    tg.axis = 'Z'
    nt.links.new(tg.outputs['Tangent'], b.inputs['Tangent'])
    return m

def prism(verts, h, loc, rz, m, parts, bevel=2.0):
    n = len(verts)
    vs = [(x, y, 0) for x, y in verts] + [(x, y, h) for x, y in verts]
    fs = [list(range(n))[::-1], list(range(n, 2 * n))] + [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    me = bpy.data.meshes.new('prism')
    me.from_pydata(vs, [], fs)
    me.update()
    o = bpy.data.objects.new('prism', me)
    bpy.context.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (0, 0, rz)
    b = o.modifiers.new('b', 'BEVEL')
    b.width = bevel
    b.segments = 4
    for pl in me.polygons:
        pl.use_smooth = True
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

def bow_bell(parts, x, y, gold, k=1.7):
    # 리본 매듭(빨강+초록)과 금색 종. k = 크기 배율
    red = mat('ribred', (0.55, 0.02, 0.03), 0.0, 0.55, 0.0)
    grn = mat('ribgrn', (0.03, 0.30, 0.10), 0.0, 0.55, 0.0)
    z = 72
    for ang, m, dx in [(35, red, -17), (-35, grn, 17)]:
        o = sph(14 * k, (x + dx * k, y + 6 * k, z), (1.7, 0.75, 0.4), m, parts)
        o.rotation_euler = (0, 0, math.radians(ang))
    for ang, m, dx in [(-20, red, -8), (20, grn, 9)]:
        box((9 * k, 38 * k, 3), (x + dx * k, y - 22 * k, z - 4), math.radians(ang), m, parts, 1)
    sph(8 * k, (x, y + 4 * k, z + 2), (1, 1, 0.7), red, parts)
    bx, by = x + 34 * k * 0.9, y - 34 * k * 0.9
    sph(17 * k, (bx, by, 50), (1, 1, 0.95), gold, parts)
    tor(15 * k, 3.2 * k, (bx, by, 36), gold, parts)
    tor(5 * k, 1.8 * k, (bx, by, 50 + 17 * k * 0.9), gold, parts)
    box((3, 15 * k, 3), (bx, by - 10 * k, 50 + 17 * k * 0.75), 0, mat('slit', (0.05, 0.03, 0.01), 0, 0.5), parts, 0.5)

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
    cu.bevel_depth = 17
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
    prism([(-14, -12), (14, -12), (27, 92), (-27, 92)], 9, (ex, ey, 40), rz, gold, parts, 4)
    box((34, 46, 16), (ex + d.x * 82, ey + d.y * 82, 30), rz, brass, parts, 4)
    side = Vector((-d.y, d.x))
    box((5, 54, 5), (ex + d.x * 26 + side.x * 36, ey + d.y * 26 + side.y * 36, 46), rz + 0.5, gold, parts, 2)
    bow_bell(parts, 60, -585, gold)

def knobs(parts):
    # 레퍼런스 구조: 에나멜 링 + 어두운 홈 + 평평한 결 금속 캡 + 어두운 눈금 점 9개 + 작은 지시 조각
    dark = mat('dot', (0.12, 0.07, 0.03), 0.0, 0.6)
    groove = mat('groove', (0.02, 0.015, 0.01), 0.0, 0.5)
    spec = [
        (mat('ring_g1', (0.02, 0.28, 0.10), 0.0, 0.10, 1.0), turned_metal('cap_r', (0.78, 0.03, 0.04), 0.30), (0.95, 0.75, 0.4)),
        (mat('ring_g2', (0.01, 0.20, 0.07), 0.0, 0.10, 1.0), turned_metal('cap_g', (0.05, 0.50, 0.12), 0.30), (0.9, 0.2, 0.25)),
        (mat('ring_r', (0.50, 0.02, 0.03), 0.0, 0.10, 1.0), turned_metal('cap_au', (0.92, 0.72, 0.36), 0.28), (0.7, 0.1, 0.08)),
    ]
    for i, (ring, cap, chip) in enumerate(spec):
        x = i * 200
        cyl(44, 14, (x, 0, 7), ring, parts, 6)
        cyl(35.5, 1.0, (x, 0, 14.3), groove, parts, 0.2)
        cyl(33, 3.0, (x, 0, 15.5), cap, parts, 0.8)
        a0 = math.radians(125)
        o = sph(3.6, (x + 22 * math.cos(a0), 22 * math.sin(a0), 17.5), (1.0, 0.55, 0.3), mat('chip%d' % i, chip, 0.0, 0.3, 1.0), parts)
        o.rotation_euler = (0, 0, a0)
        for k in range(9):
            a = math.radians(215 - k * 31)
            sph(2.0, (x + 53 * math.cos(a), 53 * math.sin(a), 1.5), (1, 1, 0.6), dark, parts)

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
