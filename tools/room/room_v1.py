# 룸 뷰 1차: 베이 창 + 윈도 시트 + 커튼 + 턴테이블 캐비닛 + 바닥 스탠드 + 줄조명 + 책장.
# 배치는 roomview_layout_v1 기준. 좌표: x 오른쪽, y 창 쪽(안쪽), z 위. 단위 m.
# 실행: blender -b -P room_v1.py -- --outdir render [--res 1200] [--samples 128] [--presets day,golden,night]
import bpy, bmesh, math, sys, os, json, random, urllib.request
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(k, d): return argv[argv.index(k) + 1] if k in argv else d
outdir = arg("--outdir", "render"); RES = int(arg("--res", "1200")); SPP = int(arg("--samples", "128"))
PRESETS = arg("--presets", "day,golden,night").split(",")
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

# ───────── 재질 ─────────
M_floor = tex_mat("floor", polyhaven(("wood_floor_worn", "wood_floor", "laminate_floor_02", "brown_floor_tiles", "wood_planks")), 1.0, (.85, .62, .45), fallback=(.32, .18, .09))
M_walnut = tex_mat("walnut", polyhaven(("wood_table_001", "dark_wood")), 1.2, (.78, .55, .40), .9, fallback=(.20, .10, .05))
M_wall = add_bump(mat("wall", (.80, .73, .62), .92), 18, .08)
M_trim = mat("trim", (.86, .82, .74), .45)
M_cush = add_bump(mat("cushion", (.86, .82, .74), 1., **{"Sheen Weight": .6, "Sheen Tint": (1, .95, .9, 1)}), 140, .25, .003)
M_cush2 = add_bump(mat("cushion2", (.80, .72, .60), 1., **{"Sheen Weight": .6}), 140, .25, .003)
M_knit = add_bump(mat("knit", (.62, .45, .38), 1., **{"Sheen Weight": .8}), 70, .6, .006)
M_curtain = thin_mat("curtain", (.88, .84, .76), .5)
M_shade = thin_mat("shade", (.95, .88, .74), .6, emit_key="shade")
M_leaf = thin_mat("leaf", (.16, .30, .08), .35)
M_pot = mat("pot", (.55, .28, .17), .8)
M_black = mat("black", (.012, .012, .014), .25)
M_cream = mat("cream_plastic", (.80, .76, .68), .35)
M_alu = mat("alu", (.85, .85, .86), .25, 1.)
M_label = mat("label", (.62, .20, .10), .7)
M_cup = mat("porcelain", (.92, .90, .86), .15, **{"Coat Weight": .5})
M_coffee = mat("coffee", (.06, .025, .01), .05)
M_paper = add_bump(mat("paper", (.90, .87, .80), .85), 600, .1, .0004)
M_brass = mat("brass", (.85, .62, .32), .3, 1.)
M_bulb = mat("bulb", (1, .7, .35), .3); EMIT["fairy"] = None
M_rug = add_bump(mat("rug", (.70, .62, .52), 1.), 260, .4, .003)

# 줄조명 전구: 발광 재질
nt = M_bulb.node_tree; b = nt.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1., .62, .28, 1)
b.inputs["Emission Strength"].default_value = 0; EMIT["fairy"] = b

# ───────── 방 구조 ─────────
H = 2.7; Y0 = 2.5; BX = 1.25; BY = 3.2      # 베이: 가운데 면 x∈[-1.25,1.25] y=3.2, 양옆 면은 (±2.0,2.5)→(±1.25,3.2)
WALL_T = .14; SILL = .62; HEAD = 2.32
faces = [((-2.0, Y0), (-BX, BY)), ((-BX, BY), (BX, BY)), ((BX, BY), (2.0, Y0))]
floor = box("floor", (0, .4, -.02), (5.2, 6.0, .04), M_floor)
link_ceiling = box("ceiling", (0, .4, H + .02), (5.2, 6.0, .04), M_wall)
box("wall_L", (-2.42, .1, H / 2), (.1, 4.8, H), M_wall); box("wall_R", (2.42, .1, H / 2), (.1, 4.8, H), M_wall)
box("wall_front", (0, -2.3, H / 2), (5.0, .1, H), M_wall)
box("return_L", (-2.21, Y0 + .05, H / 2), (.42, .1, H), M_wall); box("return_R", (2.21, Y0 + .05, H / 2), (.42, .1, H), M_wall)
box("crown", (0, .1, H - .05), (4.8, 4.8, .02), M_trim)   # 천장 몰딩 대용(아래 면이 보이는 띠)
for side in (-1, 1):
    box(f"crownL{side}", (side * 2.36, .1, H - .06), (.04, 4.8, .1), M_trim)

def along(a, b, t): return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
mull = []
for i, (a, b2) in enumerate(faces):
    L = math.dist(a, b2); ang = math.atan2(b2[1] - a[1], b2[0] - a[0]); mid = along(a, b2, .5)
    nrm = (-math.sin(ang), math.cos(ang))      # 바깥 방향
    c = lambda t, z, off=0.: (along(a, b2, t)[0] + nrm[0] * off, along(a, b2, t)[1] + nrm[1] * off, z)
    box(f"under{i}", c(.5, SILL / 2, .02), (L + .02, WALL_T, SILL), M_wall, ang)
    box(f"over{i}", c(.5, (HEAD + H) / 2, .02), (L + .02, WALL_T, H - HEAD), M_wall, ang)
    # 창틀·창살 (흰 나무)
    for t in (0, 1): box(f"post{i}{t}", c(t, (SILL + HEAD) / 2), (.09, .12, HEAD - SILL), M_trim, ang)
    box(f"head{i}", c(.5, HEAD - .03), (L, .12, .07), M_trim, ang)
    box(f"sill{i}", c(.5, SILL - .02, -.05), (L + .04, .26, .04), M_trim, ang)    # 화분이 놓이는 창턱
    nv = 4 if i == 1 else 2
    for k in range(1, nv): box(f"mv{i}{k}", c(k / nv, (SILL + HEAD) / 2), (.05, .07, HEAD - SILL), M_trim, ang)
    box(f"transom{i}", c(.5, 1.82), (L, .08, .06), M_trim, ang)
    for z in (1.0, 1.4, 2.08): box(f"mh{i}{z}", c(.5, z), (L, .05, .03), M_trim, ang)
    # 창턱 화분 + 잎
    n_pot = 5 if i == 1 else 2
    for k in range(n_pot):
        px, py, _ = c((k + .5) / n_pot, 0, -.05)
        cyl(f"pot{i}{k}", (px, py, SILL + .06), .07, .12, M_pot, r2=.085)
        bm = bmesh.new()
        for _ in range(26):
            th = random.uniform(0, 6.28); ph = random.uniform(.1, 1.2); ln = random.uniform(.08, .22)
            base = Vector((px, py, SILL + .13)); tip = base + Vector((math.cos(th) * math.sin(ph), math.sin(th) * math.sin(ph), math.cos(ph))) * ln
            side = Vector((-math.sin(th), math.cos(th), 0)) * random.uniform(.02, .035)
            v = [bm.verts.new(p) for p in (tip - (tip - base) * .9, tip - (tip - base) * .5 + side, tip, tip - (tip - base) * .5 - side)]
            bm.faces.new(v)
        mesh_obj(f"leaves{i}{k}", bm, M_leaf)

# 바깥: 나무 잎 카드(햇빛을 걸러 바닥에 잎 그림자) + 먼 숲
def foliage_card(name, c, w, h, scale, dens, colr):
    o = box(name, c, (w, .01, h)); m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = scale; nz.inputs["Detail"].default_value = 8
    nz.inputs["Roughness"].default_value = .65
    ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].position = dens; ramp.color_ramp.elements[1].position = dens + .04
    ramp.color_ramp.elements[0].color = (1, 1, 1, 1); ramp.color_ramp.elements[1].color = (0, 0, 0, 1)
    tr = nt.nodes.new("ShaderNodeBsdfTransparent"); lf = nt.nodes.new("ShaderNodeBsdfTranslucent"); dfs = nt.nodes.new("ShaderNodeBsdfDiffuse")
    lf.inputs["Color"].default_value = (*colr, 1); dfs.inputs["Color"].default_value = (*[x * .7 for x in colr], 1)
    ml = nt.nodes.new("ShaderNodeMixShader"); ml.inputs[0].default_value = .5; nt.links.new(dfs.outputs[0], ml.inputs[1]); nt.links.new(lf.outputs[0], ml.inputs[2])
    mx = nt.nodes.new("ShaderNodeMixShader"); nt.links.new(nz.outputs["Fac"], ramp.inputs[0]); nt.links.new(ramp.outputs[0], mx.inputs[0])
    nt.links.new(ml.outputs[0], mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2]); nt.links.new(mx.outputs[0], out.inputs[0])
    o.data.materials.append(m); return o
foliage_card("trees_near", (-.8, 4.8, 3.3), 8, 3.4, 1.8, .56, (.30, .40, .12))
foliage_card("trees_far", (0, 10.0, 2.4), 18, 6, 1.1, .47, (.16, .24, .08)).visible_shadow = False   # 먼 숲은 배경만, 햇빛은 막지 않음

# ───────── 윈도 시트 ─────────
SEAT_D = .58; SEAT_Z = .46
def inset(a, b2, d):   # 면을 방 안쪽으로 d만큼 옮긴 선
    ang = math.atan2(b2[1] - a[1], b2[0] - a[0]); n = (math.sin(ang), -math.cos(ang))
    return (a[0] + n[0] * d, a[1] + n[1] * d), (b2[0] + n[0] * d, b2[1] + n[1] * d)
def bay_poly(d):       # 베이 안쪽 d 위치의 꺾인 선(모서리 교차점 계산)
    lines = [inset(a, b2, d) for a, b2 in faces]
    def isect(l1, l2):
        (x1, y1), (x2, y2) = l1; (x3, y3), (x4, y4) = l2
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4); t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return [lines[0][0], isect(lines[0], lines[1]), isect(lines[1], lines[2]), lines[2][1]]
def prism(name, outer, inner, z0, z1, m, bevel=0.):
    bm = bmesh.new(); ring = outer + inner[::-1]
    bot = [bm.verts.new((x, y, z0)) for x, y in ring]; f = bm.faces.new(bot)
    r = bmesh.ops.extrude_face_region(bm, geom=[f]); top = [v for v in r["geom"] if isinstance(v, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, z1 - z0), verts=top); bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = mesh_obj(name, bm, m)
    if bevel: mb = o.modifiers.new("bv", "BEVEL"); mb.width = bevel; mb.segments = 3
    return o
outer = bay_poly(WALL_T / 2); inner = bay_poly(SEAT_D)
prism("seat_base", outer, inner, 0, SEAT_Z - .08, M_walnut)
prism("seat_top", outer, bay_poly(SEAT_D + .02), SEAT_Z - .08, SEAT_Z - .05, M_walnut, .008)
o = prism("seat_pad", bay_poly(WALL_T / 2 + .02), bay_poly(SEAT_D - .03), SEAT_Z - .05, SEAT_Z + .06, M_cush, .03)
for p in o.data.polygons: p.use_smooth = True
# 등 쿠션 (창에 기댐)
for (x, y, rz, m) in ((-1.55, 2.78, math.radians(45), M_cush), (-.75, 3.0, 0, M_cush2), (-.05, 3.0, 0, M_cush), (.85, 3.0, 0, M_cush2), (1.6, 2.72, -math.radians(45), M_cush)):
    pillow(f"pillow{x}", (x, y, SEAT_Z + .25), (.5, .16, .42), m, rz).rotation_euler.x = -.18
# 니트 담요 (쿠션 위에서 앞으로 흘러내림)
bm = bmesh.new(); nu, nv = 24, 30; grid = []
for j in range(nv):
    row = []
    for i in range(nu):
        u = i / (nu - 1); v = j / (nv - 1); x = .25 + u * .7; s = v * 1.05
        if s < .45: y, z = 2.85 - s, SEAT_Z + .08
        else:
            k = s - .45; y = 2.40 - math.sin(min(k / .3, 1) * math.pi / 2) * .1 - max(k - .3, 0) * .15; z = SEAT_Z + .08 - min(k, .3) * 1.1 - max(k - .3, 0) * .4
        z += .015 * math.sin(u * 19 + v * 7) + .02 * math.sin(v * 11)
        row.append(bm.verts.new((x + .03 * math.sin(v * 9), y, z)))
    grid.append(row)
for j in range(nv - 1):
    for i in range(nu - 1): bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
o = mesh_obj("blanket", bm, M_knit); o.modifiers.new("sol", "SOLIDIFY").thickness = .02
for p in o.data.polygons: p.use_smooth = True
# 펼친 책 + 트레이 위 커피잔
box("book_L", (-.62, 2.72, SEAT_Z + .075), (.17, .23, .015), M_paper, .25); box("book_R", (-.45, 2.76, SEAT_Z + .075), (.17, .23, .015), M_paper, .25)
box("tray", (-.25, 2.62, SEAT_Z + .07), (.3, .2, .02), M_walnut, -.1, .004)
cyl("cup", (-.27, 2.62, SEAT_Z + .125), .04, .085, M_cup); cyl("coffee", (-.27, 2.62, SEAT_Z + .16), .036, .004, M_coffee)
cyl("saucer", (-.27, 2.62, SEAT_Z + .084), .07, .008, M_cup)

# ───────── 커튼 (양 끝, 주름) ─────────
def curtain(name, x0, x1, y, inward):
    bm = bmesh.new(); nu, nv = 40, 30; g = []
    for j in range(nv):
        z = .05 + (H - .2) * j / (nv - 1); row = []
        for i in range(nu):
            u = i / (nu - 1); x = x0 + (x1 - x0) * u
            row.append(bm.verts.new((x, y + inward * (.035 * math.sin(u * 9 * math.pi) + .01 * math.sin(u * 23 + z * 3)), z)))
        g.append(row)
    for j in range(nv - 1):
        for i in range(nu - 1): bm.faces.new((g[j][i], g[j][i + 1], g[j + 1][i + 1], g[j + 1][i]))
    o = mesh_obj(name, bm, M_curtain)
    for p in o.data.polygons: p.use_smooth = True
    return o
curtain("curtain_L", -2.36, -1.92, Y0 - .1, 1); curtain("curtain_R", 1.92, 2.36, Y0 - .1, 1)
for s in (-1, 1): cyl(f"rod{s}", (s * 2.14, Y0 - .1, H - .1), .012, .5, M_brass).rotation_euler.y = math.pi / 2

# ───────── 턴테이블 캐비닛 (오른쪽 앞) ─────────
CX, CY = 1.25, 1.3
box("cabinet", (CX, CY, .3), (.95, .45, .6), M_walnut, 0, .006)
box("cab_top", (CX, CY, .61), (.99, .49, .025), M_walnut, 0, .005)
for k in (-1, 1): box(f"cab_leg{k}", (CX + k * .42, CY, .02), (.04, .4, .04), M_brass)
box("plinth", (CX - .08, CY, .67), (.44, .34, .09), M_cream, 0, .01)
cyl("platter", (CX - .13, CY, .725), .145, .02, M_alu, 96)
cyl("lp", (CX - .13, CY, .737), .148, .004, M_black, 96); cyl("lp_label", (CX - .13, CY, .7395), .05, .0012, M_label, 64)
cyl("spindle", (CX - .13, CY, .745), .004, .02, M_alu, 16)
cyl("arm_base", (CX + .09, CY + .1, .73), .025, .03, M_alu)
arm = cyl("arm", (CX + .03, CY + .02, .75), .005, .26, M_alu, 16); arm.rotation_euler = (math.radians(90), 0, math.radians(35)); arm.rotation_mode = "XYZ"
arm.rotation_euler = (math.radians(90), 0, math.radians(-145) + math.pi)
box("headshell", (CX - .055, CY - .075, .745), (.025, .045, .01), M_alu, math.radians(35))
# 탁상시계 (시간 스위치)
box("clock", (CX + .37, CY - .05, .7), (.12, .07, .14), M_brass, -.2, .01)
cyl("clock_face", (CX + .366, CY - .087, .71), .045, .004, M_cup).rotation_euler = (math.radians(90), 0, -.2)

# ───────── 바닥 스탠드 (왼쪽, 종이 갓) ─────────
LX, LY = -1.75, 1.75
cyl("lamp_base", (LX, LY, .015), .15, .03, M_brass); cyl("lamp_pole", (LX, LY, .75), .012, 1.46, M_brass, 16)
bm = bmesh.new(); bmesh.ops.create_cone(bm, cap_ends=False, segments=64, radius1=.24, radius2=.17, depth=.32)
bmesh.ops.translate(bm, vec=(LX, LY, 1.55), verts=bm.verts); o = mesh_obj("lamp_shade", bm, M_shade)
for p in o.data.polygons: p.use_smooth = True
lamp = link(bpy.data.objects.new("lamp_light", bpy.data.lights.new("lamp_light", "POINT"))); lamp.location = (LX, LY, 1.52)
lamp.data.shadow_soft_size = .06; lamp.data.color = (1., .72, .45)

# ───────── 줄조명 (왼쪽 커튼 앞, 늘어진 전구) ─────────
bm = bmesh.new()
for k in range(46):
    t = k / 45; x = -2.2 + .12 * math.sin(t * 13); y = Y0 - .25 + .05 * math.cos(t * 7); z = H - .15 - t * 2.1
    m4 = Matrix.Translation((x, y, z)); bmesh.ops.create_icosphere(bm, subdivisions=2, radius=.012, matrix=m4)
mesh_obj("fairy_bulbs", bm, M_bulb)

# ───────── 책장 (오른쪽 벽) ─────────
BXs = 2.2
box("shelf_back", (2.36, .9, 1.1), (.02, 1.6, 2.2), M_walnut)
for s in (-1, 1): box(f"shelf_side{s}", (BXs, .9 + s * .8, 1.1), (.32, .03, 2.2), M_walnut)
book_mats = [mat(f"book{i}", c, .7) for i, c in enumerate([(.45, .12, .08), (.12, .22, .32), (.70, .62, .46), (.22, .32, .18), (.60, .45, .18), (.85, .80, .70)])]
for zi in range(6):
    z = .05 + zi * .37; box(f"shelf{zi}", (BXs, .9, z), (.32, 1.6, .025), M_walnut)
    y = .13
    while y < 1.64:
        w = random.uniform(.025, .05); h = random.uniform(.2, .31); lean = random.random() < .06
        b3 = box(f"bk{zi}_{y:.2f}", (BXs + .02, y + w / 2, z + .0125 + h / 2), (random.uniform(.17, .23), w, h), random.choice(book_mats))
        if lean: b3.rotation_euler.x = .12
        y += w + .003

box("rug", (-.2, 1.6, .003), (2.4, 1.6, .006), M_rug, .02)

# ───────── 세계(하늘)·햇빛·카메라 ─────────
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True; wn = world.node_tree
sky = wn.nodes.new("ShaderNodeTexSky"); sky.sky_type = "NISHITA"; sky.sun_disc = False
bg = wn.nodes["Background"]; wn.links.new(sky.outputs[0], bg.inputs[0])
sun = link(bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))); sun.data.angle = math.radians(1.5)

cam = link(bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))); scene.camera = cam
cam.data.lens = 24; cam.location = (0.1, -1.55, 1.18)
cam.rotation_euler = (Vector((0.1, 3.0, 1.12)) - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
cam.data.dof.use_dof = True; cam.data.dof.focus_distance = 3.6; cam.data.dof.aperture_fstop = 5.6

def set_sun(elev, az, energy, colr):
    # az: 해가 있는 방향(도). 0 = 창 정면(+y), 양수 = 왼쪽(-x)
    a = math.radians(az); e = math.radians(elev)
    to_sun = Vector((-math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e)))
    sun.rotation_euler = (-to_sun).to_track_quat("-Z", "Y").to_euler(); sun.data.energy = energy; sun.data.color = colr
    sky.sun_elevation = e; sky.sun_rotation = math.radians(90) + a

P = {   # 프리셋: 해(고도, 방위, 세기, 색), 하늘 세기, 노출, 스탠드, 갓 발광, 줄조명
    "day":    dict(sun=(34, 30, 3.5, (1., .96, .9)),  sky=1.0, exp=1.3, lamp=0,   shade=0,  fairy=.6),
    "golden": dict(sun=(17, 42, 6.0, (1., .52, .22)),  sky=.6,  exp=1.5, lamp=0,   shade=0,  fairy=1.5),
    "night":  dict(sun=(-8, 38, .0, (1, 1, 1)),       sky=.0,  exp=-.2, lamp=35., shade=.3, fairy=5.),
}
scene.render.engine = "CYCLES"; scene.cycles.device = "CPU"; scene.cycles.samples = SPP
scene.cycles.use_adaptive_sampling = True; scene.cycles.adaptive_threshold = .02
scene.cycles.use_denoising = True
try: scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception: pass
scene.cycles.max_bounces = 6; scene.cycles.diffuse_bounces = 4; scene.cycles.glossy_bounces = 2; scene.cycles.transparent_max_bounces = 8
scene.cycles.caustics_reflective = scene.cycles.caustics_refractive = False; scene.cycles.sample_clamp_indirect = 8
scene.render.resolution_x = RES; scene.render.resolution_y = int(RES * 10 / 16)
scene.view_settings.view_transform = "AgX"
try: scene.view_settings.look = "AgX - Medium High Contrast"
except Exception: pass
scene.render.image_settings.file_format = "PNG"
import time
for k in PRESETS:
    p = P[k]; set_sun(*p["sun"]); sun.hide_render = p["sun"][2] == 0
    bg.inputs["Strength"].default_value = p["sky"]
    if k == "night":    # 밤: 푸른 달빛 하늘
        wn.links.remove(bg.inputs[0].links[0]); bg.inputs[0].default_value = (.02, .03, .07, 1); bg.inputs["Strength"].default_value = .25
    lamp.data.energy = p["lamp"]; lamp.hide_render = p["lamp"] == 0
    EMIT["shade"].inputs["Strength"].default_value = p["shade"]; EMIT["fairy"].inputs["Emission Strength"].default_value = p["fairy"]
    scene.view_settings.exposure = p["exp"]
    scene.render.filepath = os.path.join(outdir, f"room_v1_{k}.png"); t0 = time.time()
    bpy.ops.render.render(write_still=True); info[f"time_{k}"] = round(time.time() - t0)
json.dump(info, open(os.path.join(outdir, "room_info.json"), "w"), ensure_ascii=False, indent=1)
print("ROOM DONE", info)
