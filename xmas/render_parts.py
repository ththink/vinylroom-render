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

def chaikin(v, n=3):
    # 모서리 둥글리기(코너 컷팅 반복)
    for _ in range(n):
        o = []
        for i in range(len(v)):
            a, b = v[i], v[(i + 1) % len(v)]
            o.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            o.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        v = o
    return v

def micro(m, scale=150, strength=0.04, dist=0.4):
    # 미세한 금속 질감(범프): 표면 결·잔 스크래치
    nt = m.node_tree
    b = nt.nodes['Principled BSDF']
    n = nt.nodes.new('ShaderNodeTexNoise')
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = 10
    bp = nt.nodes.new('ShaderNodeBump')
    bp.inputs['Strength'].default_value = strength
    bp.inputs['Distance'].default_value = dist
    nt.links.new(n.outputs['Fac'], bp.inputs['Height'])
    nt.links.new(bp.outputs['Normal'], b.inputs['Normal'])
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

def lathe(profile, segs, loc, rot, m, parts):
    # (반지름, 높이) 단면을 회전시켜 종 같은 회전체를 만든다
    n = len(profile)
    vs, fs = [], []
    for j in range(segs):
        a = 2 * math.pi * j / segs
        for (r, z) in profile:
            vs.append((r * math.cos(a), r * math.sin(a), z))
    for j in range(segs):
        j2 = (j + 1) % segs
        for i in range(n - 1):
            fs.append([j * n + i, j2 * n + i, j2 * n + i + 1, j * n + i + 1])
    me = bpy.data.meshes.new('lathe')
    me.from_pydata(vs, [], fs)
    me.update()
    for pl in me.polygons:
        pl.use_smooth = True
    o = bpy.data.objects.new('lathe', me)
    bpy.context.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = rot
    return link(o, parts, m)

def bell(parts, apex, gold, k=1.05):
    # 입이 카메라 쪽으로 보이게 기울어진 종: 입(어두운 안쪽) + 추 + 윗고리
    u = Vector((0.6, -0.6, 0.5)).normalized()
    origin = Vector(apex) + u * (42 * k)
    rot = u.to_track_quat('-Z', 'Y').to_euler()
    prof = [(3, 44), (7, 43), (12, 38), (15, 29), (17, 18), (20, 9), (25, 3.5), (28.5, 0), (27, -1.2), (25, 0)]
    prof = [(r * k, z * k) for r, z in prof]
    lathe(prof, 56, origin, rot, gold, parts)
    dk = mat('bellin', (0.03, 0.015, 0.006), 0.0, 0.5)
    o = cyl(24.5 * k, 1.0, (0, 0, 0), dk, parts, 0.2)
    o.location = origin + u * (0.5 * k)
    o.rotation_euler = rot
    s = sph(6.5 * k, (0, 0, 0), (1, 1, 1), gold, parts)
    s.location = origin + u * (2 * k)
    h = tor(5.5 * k, 1.8 * k, (0, 0, 0), gold, parts)
    h.location = Vector(apex) - u * (3 * k)
    h.rotation_euler = rot

def bell_only(parts):
    # 종 단독 렌더: 윗고리(apex)가 회전 중심. 톤암 피벗 기준 apex = (118, -629)
    gold = micro(mat('gold', (0.80, 0.52, 0.15), 1.0, 0.18), 150, 0.03)
    bell(parts, (118, -629, 62), gold, 1.3)

def tonearm(parts):
    gold = micro(mat('gold', (0.80, 0.52, 0.15), 1.0, 0.18), 150, 0.03)
    brass = mat('brass', (0.30, 0.18, 0.06), 1.0, 0.3)
    pts = [(0, 0), (40, -150), (76, -336), (66, -500), (43, -662), (-2, -724), (-34, -772)]
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
    # 헤드셸: 레퍼런스처럼 위가 좁고 아래가 넓은 방패꼴 판 + 슬롯 3개(은색 나사) + 갈색 붉은 아랫단 + 바늘
    cr, sr = math.cos(rz), math.sin(rz)
    def l2w(lx, ly):
        return (ex + lx * cr - ly * sr, ey + lx * sr + ly * cr)
    wine = mat('wine', (0.32, 0.04, 0.03), 0.6, 0.35)
    silver = mat('silver', (0.9, 0.9, 0.92), 1.0, 0.22)
    slotm = mat('slot', (0.10, 0.05, 0.02), 0.0, 0.5)
    # 위가 좁고 길게 퍼지는 방패꼴(오각형) → 모서리 살짝 깎기
    shell = chaikin([(-24, -8), (24, -8), (37, 56), (38, 98), (-32, 106), (-42, 60)], 1)
    inner = [(x * 0.86, y * 0.86 + 7) for x, y in shell]
    bronze = micro(mat('bronze', (0.50, 0.33, 0.12), 1.0, 0.30), 110, 0.05)
    bronze2 = micro(mat('bronze2', (0.62, 0.42, 0.17), 1.0, 0.22), 110, 0.04)
    brass2 = mat('brass2', (0.55, 0.36, 0.12), 1.0, 0.25)
    prism([(x * 1.05, y * 1.03 - 1) for x, y in shell], 8, (ex, ey, 33), rz, wine, parts, 1.8)
    prism(shell, 11, (ex, ey, 40), rz, bronze, parts, 3.0)
    prism(inner, 1.4, (ex, ey, 51), rz, bronze2, parts, 0.5)
    # 슬롯 3개는 판 안쪽에 여유를 두고 배치 (슬롯 반길이 약 10)
    for (sx, sy, sa) in [(8, 22, 28), (-18, 56, 34), (16, 80, 28)]:
        wx, wy = l2w(sx, sy)
        o = cyl(5.0, 1.2, (wx, wy, 52.6), slotm, parts, 0.3)
        o.scale = (1.0, 2.9, 1.0)
        o.rotation_euler = (0, 0, rz + math.radians(sa))
        # 슬롯 안 황동 블록과 은색 나사(머리 홈 포함)
        bx2, by2 = l2w(sx + 0.8, sy + 4.5)
        box((4.2, 9.0, 1.2), (bx2, by2, 53.0), rz + math.radians(sa), brass2, parts, 0.4)
        wx2, wy2 = l2w(sx - 0.6, sy - 3.2)
        cyl(3.5, 1.6, (wx2, wy2, 53.4), silver, parts, 0.5)
        t2 = tor(3.6, 0.6, (wx2, wy2, 53.2), slotm, parts)
        box((4.6, 0.7, 0.8), (wx2, wy2, 54.3), rz + math.radians(sa + 40), slotm, parts, 0.1)
    mx, my = l2w(-27, 82)
    sph(2.6, (mx, my, 52.6), (1, 0.6, 0.3), silver, parts)
    # 암과 이어지는 통(칼라): 판 목 너비(±24) 안에 들어가는 크기
    d3 = Vector((d.x, d.y, 0))
    bx, by = l2w(0, -14)
    rot3 = d3.to_track_quat('Z', 'Y').to_euler()
    o = cyl(18, 26, (bx, by, 48), gold, parts, 4)
    o.rotation_euler = rot3
    r2 = tor(17.2, 2.4, (bx + d.x * 9, by + d.y * 9, 48), gold, parts)
    r2.rotation_euler = rot3
    r3 = tor(17.2, 2.4, (bx - d.x * 9, by - d.y * 9, 48), gold, parts)
    r3.rotation_euler = rot3
    # 바늘: 판 아래에서 바깥으로 나오는 가늘고 긴 테이퍼 캔틸레버 + 끝점
    needle = mat('needle', (0.45, 0.05, 0.04), 0.9, 0.22)
    nx, ny = l2w(6, 96)
    prism([(-3.2, 0), (3.2, 0), (1.2, 60), (-1.2, 60)], 3.2, (nx, ny, 32), rz + math.radians(-16), needle, parts, 0.6)

def knobs(parts):
    # 레퍼런스 구조: 에나멜 링 + 어두운 홈 + 평평한 결 금속 캡 + 어두운 눈금 점 9개 + 작은 지시 조각
    dark = mat('dot', (0.12, 0.07, 0.03), 0.0, 0.6)
    groove = mat('groove', (0.02, 0.015, 0.01), 0.0, 0.5)
    spec = [
        (mat('ring_g1', (0.002, 0.085, 0.03), 0.0, 0.22, 0.22), turned_metal('cap_r', (0.78, 0.03, 0.04), 0.30), (0.95, 0.75, 0.4)),
        (mat('ring_g2', (0.002, 0.065, 0.024), 0.0, 0.22, 0.22), turned_metal('cap_g', (0.05, 0.50, 0.12), 0.30), (0.9, 0.2, 0.25)),
        (mat('ring_r', (0.19, 0.005, 0.008), 0.0, 0.22, 0.22), turned_metal('cap_au', (0.92, 0.72, 0.36), 0.28), (0.7, 0.1, 0.08)),
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
    run_job('tonearm', tonearm, 0, -400, 600, 1040, a)
    run_job('knobs', knobs, 200, 0, 600, 200, a)
    run_job('bell', bell_only, 148, -659, 240, 240, a)
    print('done')
