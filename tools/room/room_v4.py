# 룸 뷰 4차: 오후 3시 햇살(해 2배+), 밝은 벽·천장·마루
# 배치는 roomview_layout_v1 기준. 좌표: x 오른쪽, y 창 쪽(안쪽), z 위. 단위 m.
# 실행: blender -b -P room_v4.py -- --outdir render [--res 1200] [--samples 128] [--presets day,golden,night]
import bpy, bmesh, math, sys, os, json, random, urllib.request
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(k, d): return argv[argv.index(k) + 1] if k in argv else d
outdir = arg("--outdir", "render"); RES = int(arg("--res", "1200")); SPP = int(arg("--samples", "128"))
PRESETS = arg("--presets", "afternoon").split(",")
os.makedirs(outdir, exist_ok=True); info = {}; random.seed(11)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene; col = scene.collection

# ───────── 공통 도구 ─────────
def link(o): col.objects.link(o); return o
def mesh_obj(name, bm, mat=None):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = link(bpy.data.objects.new(name, me))
    if mat: o.data.materials.append(mat)
    for p in o.data.polygons: p.use_smooth = False
    return o
def box(name, c, s, mat=None, rz=0., bevel=0., smooth=False):
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=s, verts=bm.verts)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rz, 3, 'Z'), verts=bm.verts)
    bmesh.ops.translate(bm, vec=c, verts=bm.verts)
    o = mesh_obj(name, bm, mat)
    if bevel:
        m = o.modifiers.new("bv", "BEVEL"); m.width = bevel; m.segments = 4 if smooth else 2
        if smooth:
            for p in o.data.polygons: p.use_smooth = True
    return o
def cyl(name, c, r, h, mat=None, seg=48, r2=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r if r2 is None else r2, depth=h)
    bmesh.ops.translate(bm, vec=c, verts=bm.verts)
    o = mesh_obj(name, bm, mat)
    for p in o.data.polygons: p.use_smooth = True
    return o
def pillow(name, c, s, mat, rz=0.):
    o = box(name, c, s, mat, rz)
    sd = o.modifiers.new("sd", "SUBSURF"); sd.levels = sd.render_levels = 3
    for p in o.data.polygons: p.use_smooth = True
    return o

def mat(name, base, rough=.6, metal=0., **kw):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    for k, v in kw.items():
        if k in b.inputs: b.inputs[k].default_value = v
    return m
def add_bump(m, scale, strength, dist=.002):
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = scale; nz.inputs["Detail"].default_value = 6
    bp = nt.nodes.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = strength; bp.inputs["Distance"].default_value = dist
    nt.links.new(nz.outputs["Fac"], bp.inputs["Height"]); nt.links.new(bp.outputs["Normal"], b.inputs["Normal"]); return m
def thin_mat(name, base, trans=.45, emit_key=None):
    # 커튼·종이 갓·잎: 앞뒤로 빛이 비치는 얇은 재질 (확산 + 반투과)
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); df = nt.nodes.new("ShaderNodeBsdfDiffuse"); tl = nt.nodes.new("ShaderNodeBsdfTranslucent")
    mx = nt.nodes.new("ShaderNodeMixShader"); df.inputs["Color"].default_value = (*base, 1); tl.inputs["Color"].default_value = (*base, 1)
    mx.inputs[0].default_value = trans; nt.links.new(df.outputs[0], mx.inputs[1]); nt.links.new(tl.outputs[0], mx.inputs[2])
    if emit_key:   # 밤 조명용 자체 발광(프리셋에서 세기 조절)
        em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Color"].default_value = (1., .62, .30, 1); em.inputs["Strength"].default_value = 0
        ad = nt.nodes.new("ShaderNodeAddShader"); nt.links.new(mx.outputs[0], ad.inputs[0]); nt.links.new(em.outputs[0], ad.inputs[1])
        nt.links.new(ad.outputs[0], out.inputs[0]); EMIT[emit_key] = em
    else: nt.links.new(mx.outputs[0], out.inputs[0])
    return m
EMIT = {}

# Poly Haven CC0 텍스처 (실패하면 단색 + 노이즈로 대체)
def polyhaven(cands, maps=(("Diffuse", "diff"), ("nor_gl", "nor"), ("Rough", "rough")), res="2k"):
    for aid in cands:
        try:
            rq = urllib.request.Request(f"https://api.polyhaven.com/files/{aid}", headers={"User-Agent": "Mozilla/5.0"})
            files = json.load(urllib.request.urlopen(rq, timeout=30)); got = {}
            for key, lab in maps:
                url = files[key][res]["jpg"]["url"]; p = f"/tmp/{aid}_{lab}.jpg"
                if not os.path.exists(p):
                    open(p, "wb").write(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read())
                got[lab] = p
            info.setdefault("textures", []).append(aid); return got
        except Exception as ex:
            info.setdefault("tex_errors", []).append(f"{aid}: {str(ex)[:60]}")
    return None
def tex_mat(name, tex, scale, tint=(1, 1, 1), rough_mul=1., fallback=(.5, .4, .3), box_proj=True):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    if not tex:
        b.inputs["Base Color"].default_value = (*fallback, 1); b.inputs["Roughness"].default_value = .55; return add_bump(m, 60, .1)
    tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (scale,) * 3
    nt.links.new(tc.outputs["Object" if box_proj else "UV"], mp.inputs["Vector"])
    imgs = {}
    for lab in ("diff", "nor", "rough"):
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(tex[lab])
        if box_proj: t.projection = "BOX"; t.projection_blend = .2
        if lab != "diff": t.image.colorspace_settings.name = "Non-Color"
        nt.links.new(mp.outputs[0], t.inputs["Vector"]); imgs[lab] = t
    mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 1
    mx.inputs["B"].default_value = (*tint, 1); nt.links.new(imgs["diff"].outputs[0], mx.inputs["A"]); nt.links.new(mx.outputs["Result"], b.inputs["Base Color"])
    nm = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(imgs["nor"].outputs[0], nm.inputs["Color"]); nt.links.new(nm.outputs[0], b.inputs["Normal"])
    rm = nt.nodes.new("ShaderNodeMath"); rm.operation = "MULTIPLY"; rm.inputs[1].default_value = rough_mul
    nt.links.new(imgs["rough"].outputs[0], rm.inputs[0]); nt.links.new(rm.outputs[0], b.inputs["Roughness"]); return m

# ═════════ v2: 정면 통창 + 거대한 나무 + 실내 식물 ═════════
def boxr(name, c, s, mat=None, rx=0., rz=0., bevel=0., sub=0):
    # 회전을 메시 안에서 먼저 적용 (v1의 쿠션 묻힘 오류 수정)
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1); bmesh.ops.scale(bm, vec=s, verts=bm.verts)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rz, 3, 'Z') @ Matrix.Rotation(rx, 3, 'X'), verts=bm.verts)
    bmesh.ops.translate(bm, vec=c, verts=bm.verts); o = mesh_obj(name, bm, mat)
    if bevel: m = o.modifiers.new("bv", "BEVEL"); m.width = bevel; m.segments = 3
    if sub:
        m = o.modifiers.new("sd", "SUBSURF"); m.levels = m.render_levels = sub
        for p in o.data.polygons: p.use_smooth = True
    return o

# ── 잎 재질: 앞면 광택 + 역광 투과, 잎마다 색 변화(꼭짓점 색 'col') ──
def leaf_mat(name, trans=.35, rough=.45):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); at = nt.nodes.new("ShaderNodeVertexColor"); at.layer_name = "col"
    pb = nt.nodes.new("ShaderNodeBsdfPrincipled"); pb.inputs["Roughness"].default_value = rough
    tl = nt.nodes.new("ShaderNodeBsdfTranslucent"); hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.inputs["Saturation"].default_value = 1.25; hs.inputs["Value"].default_value = 1.4
    mx = nt.nodes.new("ShaderNodeMixShader"); mx.inputs[0].default_value = trans
    nt.links.new(at.outputs["Color"], pb.inputs["Base Color"]); nt.links.new(at.outputs["Color"], hs.inputs["Color"]); nt.links.new(hs.outputs[0], tl.inputs["Color"])
    nt.links.new(pb.outputs[0], mx.inputs[1]); nt.links.new(tl.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], out.inputs[0]); return m
LEAF_COLS = [(.12, .26, .03), (.18, .34, .04), (.26, .42, .06), (.09, .20, .03), (.34, .46, .08)]

class Leaves:
    """잎 여러 장을 메시 하나로 모아 만든다 (빠름)."""
    def __init__(s, name, mat, cols=LEAF_COLS): s.bm = bmesh.new(); s.name = name; s.mat = mat; s.cols = cols; s.cl = s.bm.loops.layers.color.new("col")
    def add(s, base, d, up, ln, wd, n=4, bend=.25, heart=False, col=None):
        d = Vector(d).normalized(); side = d.cross(Vector(up)).normalized(); nrm = side.cross(d).normalized()
        col = col or random.choice(s.cols); jit = random.uniform(.8, 1.2); col = (*[min(1, c * jit) for c in col], 1)
        mid = []; L = []; R = []
        for i in range(n + 1):
            t = i / n; p = Vector(base) + d * ln * t - nrm * bend * ln * t * t
            w = wd * (math.sin(math.pi * min(t * (1.25 if heart else 1), 1)) ** (.6 if heart else .8)) * (1.15 if heart and t < .35 else 1)
            mid.append(s.bm.verts.new(p + nrm * .12 * wd * math.sin(math.pi * t)))   # 가운데 잎맥이 살짝 솟음
            L.append(s.bm.verts.new(p + side * w)); R.append(s.bm.verts.new(p - side * w))
        fs = []
        for i in range(n):
            for a, b in ((L, mid), (mid, R)):
                vs = [a[i], b[i], b[i + 1], a[i + 1]]
                if len(set(v.co.to_tuple(5) for v in vs)) >= 3:
                    try: fs.append(s.bm.faces.new(vs))
                    except ValueError: pass
        for f in fs:
            for lp in f.loops: lp[s.cl] = col
    def done(s):
        o = mesh_obj(s.name, s.bm, s.mat)
        for p in o.data.polygons: p.use_smooth = True
        return o

def stem_curve(name, pts_list, radius, m):
    cu = bpy.data.curves.new(name, "CURVE"); cu.dimensions = "3D"; cu.bevel_depth = radius; cu.bevel_resolution = 2; cu.use_fill_caps = True
    for pts, rads in pts_list:
        sp = cu.splines.new("POLY"); sp.points.add(len(pts) - 1)
        for p, (x, y, z), r in zip(sp.points, pts, rads): p.co = (x, y, z, 1); p.radius = r
    o = link(bpy.data.objects.new(name, cu)); o.data.materials.append(m); return o

# ───────── 재질 ─────────
M_oak = tex_mat("oak", polyhaven(("wood_table_001", "dark_wood")), 1.0, (1.6, 1.25, .88), 1.6, fallback=(.62, .44, .26))
M_walnut = tex_mat("walnut", polyhaven(("wood_table_001",)), 1.2, (.72, .50, .36), .9, fallback=(.20, .10, .05))
M_wall = add_bump(mat("sage_wall", (.68, .74, .58), .92), 18, .08)        # 세이지 그린 벽
M_wall2 = add_bump(mat("cream_wall", (.90, .87, .80), .92), 18, .08)
M_trim = mat("trim", (.84, .80, .72), .45)
M_metal = mat("rail", (.12, .12, .12), .4, .8)
M_cush = add_bump(mat("cushion", (.86, .82, .74), 1., **{"Sheen Weight": .6}), 140, .25, .003)
M_curtain = thin_mat("curtain", (.88, .84, .74), .55)
M_shade = thin_mat("shade", (.95, .88, .74), .6, emit_key="shade")
M_pot = add_bump(mat("terracotta", (.55, .27, .15), .85), 40, .2)
M_potw = mat("white_pot", (.85, .83, .78), .4)
M_black = mat("black", (.012, .012, .014), .25); M_cream = mat("cream_plastic", (.80, .76, .68), .35)
M_alu = mat("alu", (.85, .85, .86), .25, 1.); M_label = mat("label", (.62, .20, .10), .7)
M_cup = mat("porcelain", (.92, .90, .86), .15, **{"Coat Weight": .5}); M_coffee = mat("coffee", (.06, .025, .01), .05)
M_paper = add_bump(mat("paper", (.90, .87, .80), .85), 600, .1, .0004)
M_brass = mat("brass", (.85, .62, .32), .3, 1.)
M_bulb = mat("bulb", (1, .7, .35), .3); EMIT["fairy"] = M_bulb.node_tree.nodes["Principled BSDF"]
EMIT["fairy"].inputs["Emission Color"].default_value = (1., .62, .28, 1)
M_bark = add_bump(mat("bark", (.035, .028, .022), .95), 25, .8, .02)
M_stem = mat("stem", (.18, .26, .08), .6)
M_leaf = leaf_mat("leaf"); M_tree_leaf = leaf_mat("tree_leaf", .45, .55)
def shadow_pass(m, k):
    # 그림자 광선의 k만큼은 잎을 통과 → 바깥 나무가 햇빛을 다 막지 않고 얼룩진 빛을 만든다
    nt = m.node_tree; out = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"][0]; src = out.inputs[0].links[0].from_socket
    lp = nt.nodes.new("ShaderNodeLightPath"); tr = nt.nodes.new("ShaderNodeBsdfTransparent"); mx = nt.nodes.new("ShaderNodeMixShader")
    mm = nt.nodes.new("ShaderNodeMath"); mm.operation = "MULTIPLY"; mm.inputs[1].default_value = k
    nt.links.new(lp.outputs["Is Shadow Ray"], mm.inputs[0]); nt.links.new(mm.outputs[0], mx.inputs[0])
    nt.links.new(src, mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], out.inputs[0])
shadow_pass(M_tree_leaf, .75)
M_flower = mat("flower", (.95, .94, .88), .6, **{"Subsurface Weight": .3})
def gingham():
    m = bpy.data.materials.new("gingham"); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord"); a = nt.nodes.new("ShaderNodeTexWave"); c = nt.nodes.new("ShaderNodeTexWave")
    for wv, ax in ((a, "X"), (c, "Y")):
        wv.wave_type = "BANDS"; wv.bands_direction = ax; wv.wave_profile = "SAW"; wv.inputs["Scale"].default_value = 9
        nt.links.new(tc.outputs["Object"], wv.inputs["Vector"])
    ga = nt.nodes.new("ShaderNodeMath"); ga.operation = "GREATER_THAN"; ga.inputs[1].default_value = .5
    gc = nt.nodes.new("ShaderNodeMath"); gc.operation = "GREATER_THAN"; gc.inputs[1].default_value = .5
    nt.links.new(a.outputs["Fac"], ga.inputs[0]); nt.links.new(c.outputs["Fac"], gc.inputs[0])
    ad = nt.nodes.new("ShaderNodeMath"); ad.operation = "ADD"; nt.links.new(ga.outputs[0], ad.inputs[0]); nt.links.new(gc.outputs[0], ad.inputs[1])
    rp = nt.nodes.new("ShaderNodeValToRGB"); rp.color_ramp.interpolation = "CONSTANT"
    rp.color_ramp.elements[0].color = (.86, .85, .78, 1); rp.color_ramp.elements[1].position = .7; rp.color_ramp.elements[1].color = (.12, .26, .12, 1)
    e = rp.color_ramp.elements.new(.3); e.color = (.42, .55, .38, 1)
    mr = nt.nodes.new("ShaderNodeMath"); mr.operation = "DIVIDE"; mr.inputs[1].default_value = 2
    nt.links.new(ad.outputs[0], mr.inputs[0]); nt.links.new(mr.outputs[0], rp.inputs[0]); nt.links.new(rp.outputs[0], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 1; b.inputs["Sheen Weight"].default_value = .7
    return add_bump(m, 220, .3, .002)
M_ging = gingham()

# ───────── 방 ─────────
H = 3.0; WY = 3.2; WX0, WX1 = -2.05, 2.0; WTOP = 2.85; RW = 2.62
box("ceiling", (0, .4, H + .02), (5.6, 6.4, .04), M_wall2)
box("wall_L", (-RW, .4, H / 2), (.1, 5.6, H), M_wall); box("wall_R", (RW, .4, H / 2), (.1, 5.6, H), M_wall)
box("wall_front", (0, -2.6, H / 2), (5.4, .1, H), M_wall)
# 창 벽 (가운데 통창 구멍)
box("wall_win_L", ((-RW + WX0) / 2, WY, H / 2), (WX0 + RW, .16, H), M_wall)
box("wall_win_R", ((RW + WX1) / 2, WY, H / 2), (RW - WX1, .16, H), M_wall)
box("wall_win_T", ((WX0 + WX1) / 2, WY, (WTOP + H) / 2), (WX1 - WX0, .16, H - WTOP), M_wall)
box("crown", (0, .4, H - .04), (5.2, 5.6, .02), M_trim)
# 통창 문틀 (가는 금속 프레임, 열린 미닫이)
for x in (WX0, WX1, (WX0 + WX1) / 2 + .45): box(f"frame_v{x}", (x, WY, WTOP / 2), (.04, .08, WTOP), M_trim)
box("frame_top", ((WX0 + WX1) / 2, WY, WTOP), (WX1 - WX0, .1, .05), M_trim); box("frame_bot", ((WX0 + WX1) / 2, WY, .01), (WX1 - WX0, .14, .02), M_trim)
# 바닥: 헤링본 (판마다 결 방향·위치 다르게)
def herringbone(name, x0, x1, y0, y1, L=.45, W=.09, z=0.):
    bm = bmesh.new(); uv = bm.loops.layers.uv.new("UVMap"); c45 = math.cos(math.pi / 4)
    def to_w(u, v): return ((u - v) * c45, (u + v) * c45)
    R = int((abs(x0) + abs(x1) + abs(y0) + abs(y1)) / L) + 4; K = int((abs(x0) + abs(x1) + abs(y0) + abs(y1)) / W) + 4
    for r in range(-R, R):
        for k in range(-K, K):
            for (u, v, w, h, horiz) in ((r * L + k * W, -r * L + k * W, L, W, 1), (r * L + k * W - W, -r * L + k * W, W, L, 0)):
                g = .0015; corners = [(u + g, v + g), (u + w - g, v + g), (u + w - g, v + h - g), (u + g, v + h - g)]
                pts = [to_w(*cpt) for cpt in corners]
                if not any(x0 - .3 < px < x1 + .3 and y0 - .3 < py < y1 + .3 for px, py in pts): continue
                f = bm.faces.new([bm.verts.new((px + random.uniform(-.0005, .0005), py, z + random.uniform(0, .0012))) for px, py in pts])
                ou, ov = random.uniform(0, 3), random.uniform(0, 3)
                for lp, (cu, cv) in zip(f.loops, corners):
                    a, b = (cu - u, cv - v) if horiz else (cv - v, cu - u)
                    lp[uv].uv = (ou + a * .7, ov + b * .7)
    o = mesh_obj(name, bm, M_oak)
    for p in o.data.polygons: p.use_smooth = False
    return o
box("floor_base", (0, .4, -.02), (5.6, 6.6, .04), M_black)
mp_ = [n for n in M_oak.node_tree.nodes if n.type == "MAPPING"]
if mp_:   # 헤링본 판마다 UV를 쓰도록 텍스처 좌표 전환
    mp_[0].inputs["Scale"].default_value = (1, 1, 1)
    for n in M_oak.node_tree.nodes:
        if n.type == "TEX_COORD": M_oak.node_tree.links.new(n.outputs["UV"], mp_[0].inputs["Vector"])
        if n.type == "TEX_IMAGE": n.projection = "FLAT"
herringbone("floor", -RW, RW, -2.6, WY + .02)

# ───────── 발코니 ─────────
box("balcony", ((WX0 + WX1) / 2, WY + .65, -.03), (WX1 - WX0 + .6, 1.2, .06), M_oak)
RY = WY + 1.15
box("rail_top", ((WX0 + WX1) / 2, RY, 1.0), (WX1 - WX0 + .6, .04, .03), M_metal); box("rail_bot", ((WX0 + WX1) / 2, RY, .08), (WX1 - WX0 + .6, .03, .02), M_metal)
x = WX0 - .3
while x < WX1 + .3: box(f"bar{x:.2f}", (x, RY, .54), (.012, .012, .92), M_metal); x += .11

# ───────── 거대한 나무 (창 정면) ─────────
def tree(seed, root, height, n_lv=4, leaf_per=70, leaf_size=.11, spread=1.):
    rnd = random.Random(seed); splines = []; tips = []
    def grow(p, d, length, rad, lv):
        pts = [p]; rads = [rad]; cur = Vector(p); dd = Vector(d)
        seg = 6
        for i in range(seg):
            dd = (dd + Vector((rnd.uniform(-.25, .25), rnd.uniform(-.25, .25), rnd.uniform(-.1, .15) + (.05 if lv else 0)))).normalized()
            cur = cur + dd * (length / seg); pts.append(cur.copy()); rads.append(rad * (1 - .55 * (i + 1) / seg))
        splines.append((pts, rads))
        if lv >= n_lv: tips.append((cur, dd)); return
        nb = 3 if lv == 0 else rnd.randint(2, 4)
        for b in range(nb):
            k = rnd.randint(2 if lv == 0 else 3, seg); base = pts[k]
            ang = rnd.uniform(0, 6.28); tilt = rnd.uniform(.5, 1.1) * spread
            nd = (Vector(d) * math.cos(tilt) + Vector((math.cos(ang), math.sin(ang), 0)) * math.sin(tilt)).normalized()
            grow(base, nd, length * rnd.uniform(.55, .72), rads[k] * .62, lv + 1)
        tips.append((cur, dd)) if lv >= n_lv - 1 else None
    grow(Vector(root), Vector((0, 0, 1)), height, .32, 0)
    o = stem_curve(f"tree_wood{seed}", [([tuple(p) for p in pts], [r / .32 for r in rads]) for pts, rads in splines], .32, M_bark)
    lv = Leaves(f"tree_leaves{seed}", M_tree_leaf, [(.12, .26, .04), (.18, .34, .05), (.26, .40, .07), (.10, .20, .04), (.30, .42, .10)])
    for c, d in tips:
        for _ in range(leaf_per):
            off = Vector((rnd.gauss(0, .5), rnd.gauss(0, .5), rnd.gauss(0, .4)))
            dirv = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-.8, .5)))
            lv.add(c + off, dirv, Vector((0, 0, 1)), leaf_size * rnd.uniform(.8, 1.25), leaf_size * .42, n=3, bend=.15)
    lv.done(); info.setdefault("tree_tips", []).append(len(tips)); return o
tree(3, (0.3, 7.6, -1.2), 4.3, n_lv=5, leaf_per=110, leaf_size=.16)
tree(8, (-4.0, 13.0, -3.0), 4.8, n_lv=4, leaf_per=110, leaf_size=.24)
tree(5, (4.2, 12.5, -3.0), 4.6, n_lv=4, leaf_per=110, leaf_size=.24)
for o in bpy.data.objects:   # 뒤쪽 나무는 배경만, 햇빛은 막지 않음
    if o.name in ("tree_wood8", "tree_leaves8", "tree_wood5", "tree_leaves5", "tree_leaves3"): o.visible_shadow = False
# 나뭇잎 그림자 판(카메라에는 안 보임): 햇빛을 잎 모양으로 걸러 바닥에 얼룩진 빛을 만든다. 열린 비율은 dens로 조절
def gobo(c, w, h, scale, dens):
    o = box("leaf_gobo", c, (w, .01, h)); m = bpy.data.materials.new("gobo"); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); nz = nt.nodes.new("ShaderNodeTexVoronoi"); nz.feature = "SMOOTH_F1"; nz.inputs["Scale"].default_value = scale
    nz2 = nt.nodes.new("ShaderNodeTexNoise"); nz2.inputs["Scale"].default_value = scale * .35; nz2.inputs["Detail"].default_value = 6
    ad = nt.nodes.new("ShaderNodeMath"); ad.operation = "ADD"; nt.links.new(nz.outputs["Distance"], ad.inputs[0]); nt.links.new(nz2.outputs["Fac"], ad.inputs[1])
    rp = nt.nodes.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].position = dens; rp.color_ramp.elements[1].position = dens + .06
    nt.links.new(ad.outputs[0], rp.inputs[0]); tr = nt.nodes.new("ShaderNodeBsdfTransparent"); df = nt.nodes.new("ShaderNodeBsdfDiffuse"); df.inputs["Color"].default_value = (.05, .1, .02, 1)
    mx = nt.nodes.new("ShaderNodeMixShader"); nt.links.new(rp.outputs[0], mx.inputs[0]); nt.links.new(df.outputs[0], mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs[0]); o.data.materials.append(m)
    o.visible_camera = o.visible_diffuse = o.visible_glossy = o.visible_transmission = o.visible_volume_scatter = False
    o.rotation_euler.x = math.radians(-35); return o
gobo((-.2, 5.2, 3.6), 9, 5, 2.2, .72)

# ───────── 커튼 + 줄조명(커튼봉을 따라 처짐) ─────────
def curtain(name, x0, x1, y, folds=9):
    bm = bmesh.new(); nu, nv = 44, 30; g = []
    for j in range(nv):
        z = .03 + (H - .2) * j / (nv - 1); row = []
        for i in range(nu):
            u = i / (nu - 1); row.append(bm.verts.new((x0 + (x1 - x0) * u, y - (.04 * math.sin(u * folds * math.pi) + .012 * math.sin(u * 23 + z * 3)), z)))
        g.append(row)
    for j in range(nv - 1):
        for i in range(nu - 1): bm.faces.new((g[j][i], g[j][i + 1], g[j + 1][i + 1], g[j + 1][i]))
    o = mesh_obj(name, bm, M_curtain)
    for p in o.data.polygons: p.use_smooth = True
curtain("curtain_L", WX0 - .55, WX0 + .12, WY - .14); curtain("curtain_R", WX1 - .1, WX1 + .55, WY - .14)
rod = cyl("rod", (0, WY - .14, H - .12), .012, 4.4, M_brass); rod.rotation_euler.y = math.pi / 2
bm = bmesh.new(); hooks = [-2.0, -1.0, 0., 1.0, 2.0]
for a, b2 in zip(hooks, hooks[1:]):
    for k in range(10):
        t = k / 10; x = a + (b2 - a) * t; z = H - .14 - .22 * math.sin(math.pi * t)
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=.011, matrix=Matrix.Translation((x, WY - .2, z)))
mesh_obj("fairy_bulbs", bm, M_bulb)

# ───────── 데이베드 (왼쪽 벽, 깅엄 이불) ─────────
DX0, DX1, DY0, DY1 = -2.56, -1.5, -.7, 1.55
boxr("bed_frame", ((DX0 + DX1) / 2, (DY0 + DY1) / 2, .17), (DX1 - DX0, DY1 - DY0, .3), M_oak, bevel=.01)
boxr("bed_head", ((DX0 + DX1) / 2, DY1 + .02, .45), (DX1 - DX0 + .04, .05, .9), M_oak, bevel=.01)
for k in range(5): boxr(f"slat{k}", (DX0 + .1 + k * .18, DY1 + .01, .62), (.05, .06, .5), M_oak)
boxr("mattress", ((DX0 + DX1) / 2, (DY0 + DY1) / 2, .41), (DX1 - DX0 - .04, DY1 - DY0 - .04, .2), M_cush, bevel=.06)
for i, (y, rx, m) in enumerate(((DY1 - .14, -.35, M_ging), (DY1 - .3, -.28, M_cush))):
    for x in (DX0 + .25, DX1 - .25): boxr(f"pillow{i}{x}", (x, y, .62 - i * .03), (.4, .14, .32), m, rx=rx, rz=random.uniform(-.15, .15), sub=3)
bm = bmesh.new(); nu, nv = 30, 36; g = []
for j in range(nv):
    row = []
    for i in range(nu):
        u = i / (nu - 1); v = j / (nv - 1); y = DY0 - .05 + v * (DY1 - DY0 - .35)
        s = u * 1.3                                    # 매트리스 위(0~0.9) → 오른쪽 가장자리에서 아래로 흘러내림
        if s < .92: x = DX0 + .02 + s; z = .5 + .03 * math.sin(v * 8 + u * 5) + .02 * math.sin(u * 14)
        else:
            k = s - .92; x = DX1 + .03 + k * .12 + .02 * math.sin(v * 21); z = .49 - k * 1.05
        row.append(bm.verts.new((x, y + .015 * math.sin(u * 9), z + .012 * math.sin(v * 31 + u * 6))))
    g.append(row)
for j in range(nv - 1):
    for i in range(nu - 1): bm.faces.new((g[j][i], g[j][i + 1], g[j + 1][i + 1], g[j + 1][i]))
o = mesh_obj("blanket", bm, M_ging); o.modifiers.new("sol", "SOLIDIFY").thickness = .025
for p in o.data.polygons: p.use_smooth = True
# 벽 액자 3점 (식물 판화: 종이 위 잎 실루엣)
for i, (y, z, w, h) in enumerate(((.15, 1.45, .32, .42), (.62, 1.55, .3, .38), (1.05, 1.4, .36, .46))):
    boxr(f"frame{i}", (-RW + .04, y, z), (.03, w, h), M_walnut, bevel=.004); boxr(f"print{i}", (-RW + .057, y, z), (.004, w - .06, h - .06), M_paper)
    lv = Leaves(f"print_leaf{i}", M_leaf, [(.12, .24, .08)])
    for k in range(7): lv.add((-RW + .062, y, z - h * .3 + k * h * .07), (0, (-1) ** k * .8, .6), (1, 0, 0), .08, .03, n=3, bend=0)
    lv.done()

# ───────── 실내 식물 ─────────
def pot(name, c, r, h, m=M_pot):
    cyl(name, (c[0], c[1], c[2] + h / 2), r, h, m, r2=r * 1.2); cyl(name + "_soil", (c[0], c[1], c[2] + h - .01), r * 1.12, .01, mat("soil", (.06, .04, .03), 1.))
def bush(name, c, n, ln, wd, spread=.9, height=.3, flowers=0, heart=False):
    lv = Leaves(name, M_leaf); stems = []
    for _ in range(n):
        a = random.uniform(0, 6.28); t = random.uniform(.2, 1.) * spread; L = random.uniform(.6, 1.) * height
        tip = Vector(c) + Vector((math.cos(a) * t * height * .8, math.sin(a) * t * height * .8, L))
        lv.add(tip, (math.cos(a) * .7, math.sin(a) * .7, random.uniform(-.2, .6)), (0, 0, 1), ln * random.uniform(.8, 1.2), wd, n=4, bend=.3, heart=heart)
        stems.append(([tuple(c), tuple(Vector(c) + (tip - Vector(c)) * .5 + Vector((0, 0, .03))), tuple(tip)], [1, .8, .5]))
    for _ in range(flowers):
        a = random.uniform(0, 6.28); t = random.uniform(0, height * .7)
        cyl(f"{name}_fl{_}", (c[0] + math.cos(a) * t, c[1] + math.sin(a) * t, c[2] + height * random.uniform(.7, 1.05)), .022, .02, M_flower, 12, .012)
    lv.done(); stem_curve(name + "_stems", stems, .004, M_stem)
def monstera(name, c, n=9, size=.34, height=.75):
    lv = Leaves(name, M_leaf, [(.09, .22, .05), (.12, .27, .06), (.07, .19, .04)]); stems = []
    for k in range(n):
        a = k * 2.4 + random.uniform(-.3, .3); h = height * random.uniform(.55, 1.); r = random.uniform(.15, .4)
        tip = Vector(c) + Vector((math.cos(a) * r, math.sin(a) * r, h))
        stems.append(([tuple(c), tuple(Vector(c) + Vector((math.cos(a) * r * .3, math.sin(a) * r * .3, h * .7))), tuple(tip)], [1, .9, .7]))
        lv.add(tip, (math.cos(a), math.sin(a), random.uniform(-.4, .1)), (0, 0, 1), size * random.uniform(.8, 1.15), size * .45, n=6, bend=.35, heart=True)
    lv.done(); stem_curve(name + "_stems", stems, .007, M_stem)
def trailing(name, top, n_vines=6, length=1.0, side=Vector((0, 0, 0))):
    lv = Leaves(name, M_leaf, [(.16, .30, .06), (.22, .36, .08), (.12, .24, .05)]); vines = []
    for v in range(n_vines):
        a = random.uniform(0, 6.28); p = Vector(top) + Vector((math.cos(a) * .08, math.sin(a) * .08, 0)); pts = [tuple(p)]
        out = Vector((math.cos(a), math.sin(a), 0)) * .12 + side; L = length * random.uniform(.5, 1.1)
        for k in range(1, 14):
            t = k / 13; q = Vector(top) + Vector((math.cos(a) * .1, math.sin(a) * .1, 0)) + out * math.sin(t * 1.6) + Vector((.04 * math.sin(t * 9 + v), .04 * math.cos(t * 7 + v), -L * t * t * .9 - L * .1 * t))
            pts.append(tuple(q))
            if k > 1: lv.add(q, (math.cos(a + k) * .6, math.sin(a + k) * .6, -.5), (0, 0, 1), .07, .045, n=3, bend=.2, heart=True)
        vines.append((pts, [1] * len(pts)))
    lv.done(); stem_curve(name + "_vines", vines, .003, M_stem)

# ── 식물 (화면의 40% 이상이 초록이 되도록) ──
# 앞쪽 왼쪽 구석: 큰 몬스테라 + 덩굴 무더기 (사이드 테이블을 감쌈)
pot("pot_fl", (-1.85, -1.15, 0), .24, .38, M_potw); monstera("monstera_fl", (-1.85, -1.15, .36), n=14, size=.46, height=1.15)
pot("pot_fl2", (-1.35, -1.5, 0), .2, .3); bush("bush_fl2", (-1.35, -1.5, .28), 140, .2, .07, height=.95, heart=True)
# 앞쪽 오른쪽 구석: 큰 잎 화분 2개
pot("pot_fr", (1.85, -1.1, 0), .24, .36); monstera("monstera_fr", (1.85, -1.1, .34), n=13, size=.44, height=1.25)
pot("pot_fr2", (1.3, -1.5, 0), .18, .28, M_potw); bush("bush_fr2", (1.3, -1.5, .26), 120, .17, .06, height=.8)
# 창가 양쪽 큰 화분
pot("pot_win1", (-1.7, 2.8, 0), .2, .34); monstera("monstera_win", (-1.7, 2.8, .32), n=12, size=.36, height=1.0)
pot("pot_win2", (1.75, 2.75, 0), .2, .34, M_potw); bush("tall_win2", (1.75, 2.75, .32), 160, .16, .06, height=1.5, spread=.7)
pot("pot_win3", (-.9, 2.95, 0), .13, .22); bush("bush_win3", (-.9, 2.95, .2), 60, .12, .045, height=.5, heart=True)
# 발코니: 화분 줄 + 꽃 화단
for i, x in enumerate((-1.75, -1.25, -.7, -.15, .4, .95, 1.45, 1.85)):
    big = i % 3 == 0; r = .16 if big else .11
    pot(f"pot_bal{i}", (x, WY + .75 + .1 * (i % 2), 0), r, r * 1.7, M_pot if i % 2 else M_potw)
    bush(f"bush_bal{i}", (x, WY + .75 + .1 * (i % 2), r * 1.6), 90 if big else 50, .13 if big else .1, .045, height=.8 if big else .45, flowers=0 if big else 12)
boxr("planter_box", ((WX0 + WX1) / 2, RY - .12, .15), (WX1 - WX0, .22, .28), M_oak, bevel=.01)
bush("planter_flowers", ((WX0 + WX1) / 2 - 1.2, RY - .12, .28), 70, .09, .035, height=.3, spread=3, flowers=30)
bush("planter_flowers2", ((WX0 + WX1) / 2 + 1.0, RY - .12, .28), 70, .09, .035, height=.3, spread=3, flowers=30)
# 천장 행잉 화분 3개
for nm, hp, ln in (("hang1", Vector((-1.35, 1.6, 2.35)), 1.1), ("hang2", Vector((1.3, 2.3, 2.45)), .95), ("hang3", Vector((-.3, 2.75, 2.6)), .7)):
    cyl(nm + "_pot", tuple(hp), .13, .14, M_potw, r2=.1)
    for a in range(3): stem_curve(f"{nm}_rope{a}", [([(hp.x + .12 * math.cos(a * 2.1), hp.y + .12 * math.sin(a * 2.1), hp.z + .07), (hp.x, hp.y, H)], [1, 1])], .003, M_paper)
    trailing(nm + "_pothos", (hp.x, hp.y, hp.z + .07), n_vines=11, length=ln)
    bush(nm + "_top", (hp.x, hp.y, hp.z + .05), 30, .08, .045, height=.12, heart=True)
# 커튼봉 양 끝에서 늘어지는 덩굴
trailing("rod_vine_L", (WX0 - .3, WY - .2, H - .14), n_vines=6, length=1.5)
trailing("rod_vine_R", (WX1 + .3, WY - .2, H - .14), n_vines=6, length=1.3)

# ───────── 오른쪽 벽: 선반 + 책 + 덩굴 / 턴테이블 콘솔 + 의자 + LP ─────────
SX = RW - .18; book_mats = [mat(f"book{i}", c, .7) for i, c in enumerate([(.45, .12, .08), (.12, .22, .32), (.70, .62, .46), (.22, .32, .18), (.60, .45, .18), (.85, .80, .70), (.3, .4, .25)])]
for zi, z in enumerate((1.3, 1.68, 2.06, 2.44)):
    boxr(f"wshelf{zi}", (SX, 1.45, z), (.3, 1.7, .03), M_oak, bevel=.004); y = .65
    while y < 2.25:
        if random.random() < .26:
            pot(f"spot{zi}{y:.2f}", (SX, y + .07, z + .015), .06, .1); bush(f"sbush{zi}{y:.2f}", (SX, y + .07, z + .1), 26, .07, .03, height=.16, heart=random.random() < .5)
            if random.random() < .5: trailing(f"strail{zi}{y:.2f}", (SX - .03, y + .07, z + .1), n_vines=4, length=random.uniform(.3, .7), side=Vector((-.05, 0, 0)))
            y += .2; continue
        w = random.uniform(.025, .05); h = random.uniform(.18, .27)
        boxr(f"bk{zi}_{y:.2f}", (SX + .02, y + w / 2, z + .015 + h / 2), (random.uniform(.16, .22), w, h), random.choice(book_mats)); y += w + .003
pot("pot_top", (SX, .9, 2.455), .09, .14, M_potw); trailing("pothos_shelf", (SX - .02, .9, 2.58), n_vines=9, length=1.4, side=Vector((-.07, 0, 0)))
pot("pot_top2", (SX, 2.05, 2.075), .08, .12); trailing("pothos_shelf2", (SX - .02, 2.05, 2.18), n_vines=7, length=1.0, side=Vector((-.05, 0, 0)))
# 엽서·사진 (오른쪽 벽)
for k in range(9):
    boxr(f"card{k}", (RW - .052, .5 + (k % 3) * .13 + random.uniform(-.02, .02), 1.0 + (k // 3) * .1), (.003, .1, .075), random.choice(book_mats[2:] + [M_paper]), rx=random.uniform(-.06, .06))
# 턴테이블 콘솔 (오른쪽 벽에 붙임, 밝은 오크)
CX, CY = RW - .3, 1.35
boxr("console", (CX, CY, .37), (.5, 1.2, .04), M_oak, bevel=.005)
for sy in (-1, 1):
    for sx in (-1, 1): boxr(f"cleg{sx}{sy}", (CX + sx * .2, CY + sy * .55, .18), (.04, .04, .36), M_oak)
boxr("console_low", (CX, CY, .08), (.46, 1.12, .025), M_oak)
for k in range(14):   # 아래 칸 LP 재킷
    boxr(f"lp_sleeve{k}", (CX + .02, CY - .45 + k * .065, .25), (.31, .012, .31), random.choice(book_mats), rx=random.uniform(-.12, .12))
TTZ = .39
boxr("plinth", (CX - .02, CY + .15, TTZ + .045), (.34, .44, .09), M_cream, bevel=.01)
cyl("platter", (CX - .02, CY + .1, TTZ + .1), .145, .02, M_alu, 96); cyl("lp", (CX - .02, CY + .1, TTZ + .112), .148, .004, M_black, 96)
cyl("lp_label", (CX - .02, CY + .1, TTZ + .1145), .05, .0012, M_label, 64); cyl("spindle", (CX - .02, CY + .1, TTZ + .12), .004, .02, M_alu, 16)
cyl("arm_base", (CX + .1, CY + .32, TTZ + .105), .025, .03, M_alu)
stem_curve("tonearm", [([(CX + .1, CY + .32, TTZ + .125), (CX + .03, CY + .3, TTZ + .127), (CX - .06, CY + .24, TTZ + .127), (CX - .09, CY + .19, TTZ + .123)], [1, 1, 1, 1])], .005, M_alu)
boxr("clock", (CX, CY - .38, TTZ + .07), (.07, .12, .14), M_brass, rz=.25, bevel=.01)
cyl("clock_face", (CX - .037, CY - .37, TTZ + .08), .045, .004, M_cup).rotation_euler = (math.radians(90), 0, math.radians(90) + .25)
pot("pot_cab", (CX + .05, CY - .2, TTZ + .02), .06, .1); bush("bush_cab", (CX + .05, CY - .2, TTZ + .11), 26, .07, .03, height=.2, flowers=6)
# 나무 의자 + 초록 방석
CHX, CHY = CX - .62, CY - .1
boxr("chair_seat", (CHX, CHY, .45), (.42, .42, .035), M_oak, bevel=.006)
boxr("chair_cush", (CHX, CHY, .48), (.38, .38, .04), mat("green_cushion", (.18, .30, .14), 1., **{"Sheen Weight": .6}), sub=2)
for sx in (-1, 1):
    for sy in (-1, 1): boxr(f"chleg{sx}{sy}", (CHX + sx * .17, CHY + sy * .17, .22), (.03, .03, .45), M_oak)
for k in range(4): boxr(f"chback{k}", (CHX - .19, CHY - .15 + k * .1, .7), (.025, .03, .45), M_oak)
boxr("chback_top", (CHX - .19, CHY, .92), (.03, .44, .06), M_oak, bevel=.008)
# 러그 (침대 앞, 따뜻한 베이지)
boxr("rug", (-.35, .2, .004), (2.2, 1.6, .008), add_bump(mat("rug", (.78, .66, .50), 1., **{"Sheen Weight": .5}), 320, .5, .003), rz=.03)

# ───────── 바닥 스탠드 + 사이드 테이블(커피) ─────────
LX, LY = -2.25, 2.55
cyl("lamp_base", (LX, LY, .015), .15, .03, M_brass); cyl("lamp_pole", (LX, LY, .75), .012, 1.46, M_brass, 16)
bm = bmesh.new(); bmesh.ops.create_cone(bm, cap_ends=False, segments=64, radius1=.24, radius2=.17, depth=.32)
bmesh.ops.translate(bm, vec=(LX, LY, 1.55), verts=bm.verts); o = mesh_obj("lamp_shade", bm, M_shade)
for p in o.data.polygons: p.use_smooth = True
lamp = link(bpy.data.objects.new("lamp_light", bpy.data.lights.new("lamp_light", "POINT"))); lamp.location = (LX, LY, 1.52)
lamp.data.shadow_soft_size = .06; lamp.data.color = (1., .72, .45)
TX, TY = -1.2, -.85
boxr("side_table", (TX, TY, .5), (.42, .42, .04), M_oak, bevel=.005)
for sx in (-1, 1):
    for sy in (-1, 1): boxr(f"st_leg{sx}{sy}", (TX + sx * .18, TY + sy * .18, .24), (.035, .035, .48), M_oak)
boxr("st_book1", (TX - .02, TY, .54), (.24, .32, .035), book_mats[3], rz=.2); boxr("st_book2", (TX, TY + .01, .57), (.22, .3, .025), book_mats[2], rz=.05)
cyl("mug", (TX + .06, TY - .04, .64), .042, .1, M_cup); cyl("mug_coffee", (TX + .06, TY - .04, .685), .037, .004, M_coffee)
stem_curve("mug_handle", [([(TX + .1, TY - .04, .665), (TX + .135, TY - .04, .645), (TX + .1, TY - .04, .615)], [1, 1, 1])], .007, M_cup)

# ───────── 하늘(HDRI) + 해 + 카메라 ─────────
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True; wn = world.node_tree; bg = wn.nodes["Background"]
sky = wn.nodes.new("ShaderNodeTexSky"); sky.sky_type = "NISHITA"; sky.sun_disc = False; wn.links.new(sky.outputs[0], bg.inputs[0])
sun = link(bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))); sun.data.angle = math.radians(1.2)
portal = link(bpy.data.objects.new("portal", bpy.data.lights.new("portal", "AREA"))); portal.data.shape = "RECTANGLE"
portal.data.size = WX1 - WX0; portal.data.size_y = WTOP; portal.data.cycles.is_portal = True
portal.location = ((WX0 + WX1) / 2, WY - .05, WTOP / 2); portal.rotation_euler = (math.radians(-90), 0, 0)
cam = link(bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))); scene.camera = cam
cam.data.lens = 20; cam.location = (0.05, -2.2, 1.42)
cam.rotation_euler = (Vector((0.0, 3.2, 1.0)) - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
cam.data.dof.use_dof = True; cam.data.dof.focus_distance = 4.6; cam.data.dof.aperture_fstop = 4.5
def set_sun(elev, az, energy, colr):
    a = math.radians(az); e = math.radians(elev)
    to_sun = Vector((-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    sun.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler(); sun.data.energy = energy; sun.data.color = colr
    sky.sun_elevation = e; sky.sun_rotation = math.radians(90) + a
P = {
    "afternoon": dict(sun=(33, 20, 17.0, (1., .90, .74)), sky=.5, exp=1.45, lamp=0, shade=0, fairy=.6),
    "day":    dict(sun=(30, 14, 6.0, (1., .93, .80)), sky=.45, exp=1.5, lamp=0,  shade=0,  fairy=.8),
    "golden": dict(sun=(21, 16, 8.5, (1., .74, .44)), sky=.32, exp=1.75, lamp=0,  shade=0,  fairy=2.5),
    "night":  dict(sun=(-8, 24, 0., (1, 1, 1)),       sky=0., exp=.2,  lamp=30., shade=.3, fairy=6.),
}
scene.render.engine = "CYCLES"; scene.cycles.device = "CPU"; scene.cycles.samples = SPP
scene.cycles.use_adaptive_sampling = True; scene.cycles.adaptive_threshold = .02; scene.cycles.use_denoising = True
try: scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception: pass
scene.cycles.max_bounces = 6; scene.cycles.diffuse_bounces = 4; scene.cycles.glossy_bounces = 2; scene.cycles.transmission_bounces = 4
scene.cycles.caustics_reflective = scene.cycles.caustics_refractive = False; scene.cycles.sample_clamp_indirect = 8
scene.render.resolution_x = RES; scene.render.resolution_y = int(RES * 10 / 16)
scene.view_settings.view_transform = "AgX"
try: scene.view_settings.look = "AgX - Medium High Contrast"
except Exception: pass
scene.render.image_settings.file_format = "PNG"
import time
for k in PRESETS:
    p = P[k]; set_sun(*p["sun"]); sun.hide_render = p["sun"][2] == 0; bg.inputs["Strength"].default_value = p["sky"]
    if k == "night":
        if bg.inputs[0].links: wn.links.remove(bg.inputs[0].links[0])
        bg.inputs[0].default_value = (.02, .035, .08, 1); bg.inputs["Strength"].default_value = .35
    lamp.data.energy = p["lamp"]; lamp.hide_render = p["lamp"] == 0
    EMIT["shade"].inputs["Strength"].default_value = p["shade"]; EMIT["fairy"].inputs["Emission Strength"].default_value = p["fairy"]
    scene.view_settings.exposure = p["exp"]
    scene.render.filepath = os.path.join(outdir, f"room_v4_{k}.png"); t0 = time.time()
    bpy.ops.render.render(write_still=True); info[f"time_{k}"] = round(time.time() - t0)
json.dump(info, open(os.path.join(outdir, "room_info.json"), "w"), ensure_ascii=False, indent=1)
print("ROOM DONE", info)
