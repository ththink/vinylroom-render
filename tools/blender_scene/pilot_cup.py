# 파일럿: 커피잔 + 받침 + 월넛 책상 + 종이. 위에서 내려다본 구도, 왼쪽 위에서 오는 해(그림자는 오른쪽 아래).
# 실행: blender -b -P pilot_cup.py -- --outdir render
import bpy, bmesh, math, sys, os, json, urllib.request
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
outdir = argv[argv.index("--outdir") + 1] if "--outdir" in argv else "render"
os.makedirs(outdir, exist_ok=True)
info = {}

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ---------- 유틸 ----------
def principled(name, base, rough=.5, metal=0., **kw):
    m = bpy.data.materials.new(name); m.use_nodes = True
    n = m.node_tree.nodes; bsdf = n["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*base, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    for k, v in kw.items():
        if k in bsdf.inputs: bsdf.inputs[k].default_value = v
    return m

def catmull(pts, n=8):
    P = [pts[0]] + list(pts) + [pts[-1]]; out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(n):
            t = k / n; t2, t3 = t * t, t * t * t
            out.append(tuple(.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in range(2)))
    out.append(tuple(pts[-1])); return out

def lathe(name, profile, steps=128, smooth_n=8):
    pts = catmull(profile, smooth_n)
    bm = bmesh.new(); vs = [bm.verts.new((r, 0, z)) for r, z in pts]
    es = [bm.edges.new((vs[i], vs[i + 1])) for i in range(len(vs) - 1)]
    bmesh.ops.spin(bm, geom=vs + es, cent=(0, 0, 0), axis=(0, 0, 1), dvec=(0, 0, 0), angle=2 * math.pi, steps=steps, use_merge=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); scene.collection.objects.link(ob)
    for p in me.polygons: p.use_smooth = True
    return ob

# ---------- 재질 ----------
glaze = principled("glaze", (.93, .91, .86), rough=.07, **{"Specular IOR Level": .5, "IOR": 1.5, "Coat Weight": .15, "Coat Roughness": .03})
ceramic_foot = principled("foot", (.78, .74, .66), rough=.55)

def make_coffee_mat():
    m = bpy.data.materials.new("coffee"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    geo = nt.nodes.new("ShaderNodeNewGeometry"); sep = nt.nodes.new("ShaderNodeSeparateXYZ"); com = nt.nodes.new("ShaderNodeCombineXYZ")
    ln = nt.nodes.new("ShaderNodeVectorMath"); ln.operation = "LENGTH"
    mr = nt.nodes.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = 0; mr.inputs["From Max"].default_value = .041
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 90; nz.inputs["Detail"].default_value = 3
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = .0; ramp.color_ramp.elements[0].color = (.012, .004, .002, 1)
    ramp.color_ramp.elements[1].position = .86; ramp.color_ramp.elements[1].color = (.02, .007, .003, 1)
    e = ramp.color_ramp.elements.new(.965); e.color = (.30, .115, .035, 1)
    e2 = ramp.color_ramp.elements.new(1.0); e2.color = (.45, .22, .08, 1)
    mix = nt.nodes.new("ShaderNodeMath"); mix.operation = "ADD"
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    nt.links.new(sep.outputs["X"], com.inputs["X"]); nt.links.new(sep.outputs["Y"], com.inputs["Y"])
    nt.links.new(com.outputs[0], ln.inputs[0]); nt.links.new(ln.outputs["Value"], mr.inputs["Value"])
    nt.links.new(nz.outputs["Fac"], mix.inputs[1]); mix.inputs[0].default_value = 0
    nt.links.new(mr.outputs["Result"], mix.inputs[0]); mix.inputs[1].default_value = 0
    nt.links.new(mix.outputs["Value"], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], bs.inputs["Base Color"])
    bs.inputs["Roughness"].default_value = .04; bs.inputs["IOR"].default_value = 1.33
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"]); return m

# ---------- 책상(월넛): Poly Haven CC0 텍스처를 받아 보고, 안 되면 절차적 나무 ----------
def fetch_polyhaven():
    for aid in ("wood_table_001", "dark_wood", "wood_planks", "brown_planks_03", "wooden_planks"):
        try:
            req = urllib.request.Request(f"https://api.polyhaven.com/files/{aid}", headers={"User-Agent": "Mozilla/5.0"})
            files = json.load(urllib.request.urlopen(req, timeout=30))
            got = {}
            for key, lab in (("Diffuse", "diff"), ("nor_gl", "nor"), ("Rough", "rough")):
                url = files[key]["2k"]["jpg"]["url"]; path = f"/tmp/{aid}_{lab}.jpg"
                rq = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                open(path, "wb").write(urllib.request.urlopen(rq, timeout=60).read()); got[lab] = path
            info["wood_texture"] = aid; return got
        except Exception as ex:
            info.setdefault("wood_tex_errors", []).append(f"{aid}: {ex}")
    return None

def make_wood_mat(tex):
    m = bpy.data.materials.new("walnut"); m.use_nodes = True
    nt = m.node_tree; bs = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping")
    nt.links.new(tc.outputs["UV"], mp.inputs["Vector"]); mp.inputs["Scale"].default_value = (2, 2, 2)
    if tex:
        d = nt.nodes.new("ShaderNodeTexImage"); d.image = bpy.data.images.load(tex["diff"])
        n = nt.nodes.new("ShaderNodeTexImage"); n.image = bpy.data.images.load(tex["nor"]); n.image.colorspace_settings.name = "Non-Color"
        r = nt.nodes.new("ShaderNodeTexImage"); r.image = bpy.data.images.load(tex["rough"]); r.image.colorspace_settings.name = "Non-Color"
        for t in (d, n, r): nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        # 월넛 톤으로 살짝 어둡고 붉게
        mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 1
        mx.inputs["B"].default_value = (.78, .55, .40, 1)
        nt.links.new(d.outputs["Color"], mx.inputs["A"]); nt.links.new(mx.outputs["Result"], bs.inputs["Base Color"])
        nm = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(n.outputs["Color"], nm.inputs["Color"]); nt.links.new(nm.outputs["Normal"], bs.inputs["Normal"])
        nt.links.new(r.outputs["Color"], bs.inputs["Roughness"])
    else:
        mp.inputs["Rotation"].default_value = (0, 0, math.radians(90))
        wv = nt.nodes.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X"; wv.wave_profile = "SAW"
        wv.inputs["Scale"].default_value = 14; wv.inputs["Distortion"].default_value = 5; wv.inputs["Detail"].default_value = 3
        wv.inputs["Detail Scale"].default_value = 2.5
        nt.links.new(mp.outputs["Vector"], wv.inputs["Vector"])
        fine = nt.nodes.new("ShaderNodeTexNoise"); fine.inputs["Scale"].default_value = 320; fine.inputs["Detail"].default_value = 4
        mp2 = nt.nodes.new("ShaderNodeMapping"); mp2.inputs["Scale"].default_value = (1, 40, 1)
        nt.links.new(tc.outputs["UV"], mp2.inputs["Vector"]); nt.links.new(mp2.outputs["Vector"], fine.inputs["Vector"])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (.045, .020, .010, 1); ramp.color_ramp.elements[1].color = (.20, .095, .045, 1)
        e = ramp.color_ramp.elements.new(.5); e.color = (.11, .05, .024, 1)
        nt.links.new(wv.outputs["Fac"], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], bs.inputs["Base Color"])
        bm_ = nt.nodes.new("ShaderNodeBump"); bm_.inputs["Strength"].default_value = .25; bm_.inputs["Distance"].default_value = .0008
        nt.links.new(fine.outputs["Fac"], bm_.inputs["Height"]); nt.links.new(bm_.outputs["Normal"], bs.inputs["Normal"])
        bs.inputs["Roughness"].default_value = .38
        info["wood_texture"] = "procedural"
    bs.inputs["Specular IOR Level"].default_value = .45
    return m

def make_paper_mat():
    m = bpy.data.materials.new("paper"); m.use_nodes = True; nt = m.node_tree; bs = nt.nodes["Principled BSDF"]
    bs.inputs["Base Color"].default_value = (.88, .85, .78, 1); bs.inputs["Roughness"].default_value = .82
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 900; nz.inputs["Detail"].default_value = 6
    bm_ = nt.nodes.new("ShaderNodeBump"); bm_.inputs["Strength"].default_value = .15; bm_.inputs["Distance"].default_value = .0003
    nt.links.new(nz.outputs["Fac"], bm_.inputs["Height"]); nt.links.new(bm_.outputs["Normal"], bs.inputs["Normal"])
    return m

# ---------- 오브젝트 ----------
bpy.ops.mesh.primitive_plane_add(size=.9, location=(0, 0, 0)); desk = bpy.context.object; desk.name = "desk"
desk.data.materials.append(make_wood_mat(fetch_polyhaven()))

def sheet(name, w, h, loc, rot_deg, z):
    bpy.ops.mesh.primitive_plane_add(size=1, location=(loc[0], loc[1], z)); o = bpy.context.object; o.name = name
    o.scale = (w, h, 1); o.rotation_euler = (0, 0, math.radians(rot_deg)); o.data.materials.append(make_paper_mat())
    bpy.ops.object.shade_smooth(); return o
sheet("paper1", .21, .297, (-.085, .02), 14, .0004)
sheet("paper2", .21, .297, (-.05, -.03), -7, .0010)
SZ = .0016                                                         # 받침 바닥 높이(종이 위)

cup = lathe("cup", [(0, .0), (.022, .0), (.027, .0012), (.029, .0035), (.0315, .010), (.036, .024), (.0415, .044), (.0455, .060),
                    (.0468, .0628), (.0452, .0638), (.0436, .0628), (.0418, .052), (.0345, .031), (.0285, .014), (.021, .0075), (0, .0062)])
cup.location.z = SZ + .0042; cup.data.materials.append(glaze)
saucer = lathe("saucer", [(0, .0044), (.026, .0042), (.040, .0055), (.058, .0105), (.070, .0165), (.0745, .0188), (.0755, .0182), (.0742, .0165),
                          (.068, .0132), (.052, .0070), (.040, .0030), (.034, .0008), (.030, .0), (.022, .0), (0, .0)])
saucer.location.z = SZ; saucer.data.materials.append(glaze)

bpy.ops.mesh.primitive_circle_add(vertices=128, radius=.0408, fill_type="NGON", location=(0, 0, SZ + .0042 + .0515)); cof = bpy.context.object; cof.name = "coffee"
cof.data.materials.append(make_coffee_mat())

bpy.ops.curve.primitive_bezier_curve_add(location=(0, 0, SZ + .0042)); h = bpy.context.object; h.name = "handle"
sp = h.data.splines[0]; sp.bezier_points.add(2)
pts = [(.0445, 0, .049), (.0665, 0, .043), (.0655, 0, .028), (.0435, 0, .0185)]
sp.bezier_points.add(0)
while len(sp.bezier_points) < len(pts): sp.bezier_points.add(1)
for bp, p in zip(sp.bezier_points, pts):
    bp.co = p; bp.handle_left_type = bp.handle_right_type = "AUTO"
h.data.bevel_depth = .0042; h.data.bevel_resolution = 8; h.data.resolution_u = 24; h.data.use_fill_caps = True
h.data.materials.append(glaze); bpy.context.view_layer.objects.active = h; bpy.ops.object.convert(target="MESH")
for p in h.data.polygons: p.use_smooth = True

# ---------- 카메라(위에서, 약한 원근으로 컵 두께가 살짝 보임) ----------
bpy.ops.object.camera_add(location=(.0, .0, .85)); cam = bpy.context.object; cam.data.lens = 90; cam.data.sensor_width = 36
cam.rotation_euler = (0, 0, 0); scene.camera = cam
cam.data.dof.use_dof = True; cam.data.dof.focus_distance = .85 - .03; cam.data.dof.aperture_fstop = 22   # 거의 전부 또렷하게

# ---------- 월드/조명 ----------
w = bpy.data.worlds.new("w"); scene.world = w; w.use_nodes = True
bg = w.node_tree.nodes["Background"]
def set_light(kind):
    if kind == "golden":
        elev, col, strength, amb, ambcol = 26, (1.0, .70, .42), 4.2, .10, (.95, .62, .40)
    else:
        elev, col, strength, amb, ambcol = 50, (1.0, .93, .80), 3.2, .22, (.75, .82, .95)
    for o in [o for o in bpy.data.objects if o.type == "LIGHT"]: bpy.data.objects.remove(o)
    d = Vector((.707, -.707, -math.tan(math.radians(elev)))).normalized()       # 해 → 장면 방향(왼쪽 위에서 오른쪽 아래로)
    bpy.ops.object.light_add(type="SUN"); s = bpy.context.object
    s.rotation_euler = d.to_track_quat("-Z", "Y").to_euler(); s.data.energy = strength; s.data.color = col; s.data.angle = math.radians(2.2)
    bg.inputs["Color"].default_value = (*ambcol, 1); bg.inputs["Strength"].default_value = amb

# ---------- 렌더 ----------
scene.render.engine = "CYCLES"; scene.cycles.device = "CPU"
scene.cycles.samples = 96; scene.cycles.use_denoising = True
try: scene.cycles.denoiser = "OPENIMAGEDENOISE"
except Exception: pass
scene.cycles.max_bounces = 8; scene.cycles.caustics_reflective = False; scene.cycles.caustics_refractive = False
scene.render.resolution_x = 1200; scene.render.resolution_y = 1200; scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "AgX"
try: scene.view_settings.look = "AgX - Medium High Contrast"
except Exception: pass
scene.render.image_settings.file_format = "PNG"

for kind in ("golden", "day"):
    set_light(kind); scene.render.filepath = os.path.join(outdir, f"pilot_cup_{kind}.png")
    bpy.ops.render.render(write_still=True)
json.dump(info, open(os.path.join(outdir, "info.json"), "w"), ensure_ascii=False, indent=1)
print("PILOT DONE", info)
