#!/usr/bin/env python3
"""
Boss Maker build step for Super Mario Construct (v8 beta).

Replaces every Bowser frame in the game's sprite sheets with a student's
character, then bumps offline.json so browsers pick up the new art.

Usage:
    python tools/build_boss.py <game_folder> <boss_folder>

The boss folder holds the student's art. Either:
  - five PNGs named idle1, idle2, attack1, attack2, special (.png), or
  - one template sheet named sheet.png (5 equal-width boxes, left to right
    in that same order).
Optional 3rd argument: "sharp" (default) shows the SMW-style boss at the art's
own pixel size (1:1, or an exact 1/2, 1/3 for art over 100px tall), on new,
larger frames. "classic" squeezes the art into Bowser's original 58px slots.
Missing poses fall back: idle2->idle1, attack1->idle1, attack2->attack1,
special->attack1. Only idle1 is required.
"""
import sys, os, json, time
from collections import deque
import numpy as np
from PIL import Image

POSES = ["idle1", "idle2", "attack1", "attack2", "special"]
FALLBACK = {"idle2": "idle1", "attack1": "idle1", "attack2": "attack1", "special": "attack1"}
BORDER = (153, 102, 255)   # template box color, removed automatically

# ---------------------------------------------------------------- cleaning
def _label(mask):
    """8-connected components. Returns label array and list of sizes."""
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    sizes = []
    n = 0
    for y in range(H):
        for x in range(W):
            if mask[y, x] and not lab[y, x]:
                n += 1
                q = deque([(y, x)]); lab[y, x] = n; c = 0
                while q:
                    cy, cx = q.popleft(); c += 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not lab[ny, nx]:
                                lab[ny, nx] = n; q.append((ny, nx))
                sizes.append(c)
    return lab, sizes

def clean(im):
    """Remove template border lines, solid backgrounds and stray specks; crop tight."""
    a = np.array(im.convert("RGBA")).copy()
    H, W = a.shape[:2]
    # 1. solid background? (all 4 corners same opaque color) -> make transparent
    corners = [tuple(a[0, 0]), tuple(a[0, -1]), tuple(a[-1, 0]), tuple(a[-1, -1])]
    if corners.count(corners[0]) >= 3 and corners[0][3] == 255 and corners[0][:3] != BORDER:
        bg = np.array(corners[0])
        a[(np.abs(a.astype(int) - bg).sum(-1) <= 6)] = 0
    # 2. template border lines (long straight runs of the border color)
    isb = (a[..., 0] == BORDER[0]) & (a[..., 1] == BORDER[1]) & (a[..., 2] == BORDER[2]) & (a[..., 3] > 0)
    for y in range(H):
        if isb[y].sum() > 0.3 * W: a[y, isb[y]] = 0
    for x in range(W):
        if isb[:, x].sum() > 0.3 * H: a[isb[:, x], x] = 0
    # 3. stray specks: keep biggest blob + small bits sitting right next to it
    a[a[..., 3] < 40] = 0
    m = a[..., 3] > 0
    if not m.any():
        raise ValueError("image is empty after cleaning")
    lab, sizes = _label(m)
    main = int(np.argmax(sizes)) + 1
    ys, xs = np.where(lab == main)
    y0, y1, x0, x1 = ys.min() - 3, ys.max() + 3, xs.min() - 3, xs.max() + 3
    for i, s in enumerate(sizes, start=1):
        if i == main: continue
        ys, xs = np.where(lab == i)
        inside = ys.min() >= y0 and ys.max() <= y1 and xs.min() >= x0 and xs.max() <= x1
        if not inside or s < 2:
            a[lab == i] = 0
    a[a[..., 3] > 0, 3] = 255
    out = Image.fromarray(a)
    return out.crop(out.getbbox())

def split_sheet(im):
    W = im.width
    return [im.crop((round(i * W / 5), 0, round((i + 1) * W / 5), im.height)) for i in range(5)]

# ---------------------------------------------------------------- scaling
def pixel_down(im, s):
    """Shrink pixel art: premultiplied box filter, hard alpha, snap to the art's own colors."""
    W, H = im.size
    size = (max(1, round(W * s)), max(1, round(H * s)))
    a = np.array(im).astype(np.float32) / 255
    pm = np.concatenate([a[..., :3] * a[..., 3:4], a[..., 3:4]], -1)
    out = np.stack([np.array(Image.fromarray(pm[..., i]).resize(size, Image.BOX)) for i in range(4)], -1)
    al = out[..., 3:4]
    rgb = np.where(al > 1e-4, out[..., :3] / np.maximum(al, 1e-4), 0)
    src = np.array(im)
    pal = np.unique(src[src[..., 3] > 0][:, :3], axis=0).astype(np.float32) / 255
    flat = rgb.reshape(-1, 3)
    idx = np.concatenate([((flat[i:i + 4096, None, :] - pal[None]) ** 2).sum(-1).argmin(1)
                          for i in range(0, len(flat), 4096)])
    rgb = pal[idx].reshape(rgb.shape)
    res = np.zeros(out.shape, np.uint8)
    res[..., :3] = (rgb * 255).round()
    res[..., 3] = (out[..., 3] > 0.45) * 255
    return Image.fromarray(res)

def block_down(im, k):
    """Shrink by a whole number k: each k x k block becomes its most common color.
    No blending, so the art stays as crisp as the game's own sprites."""
    if k <= 1: return im
    a = np.array(im.convert("RGBA"))
    H, W = a.shape[:2]; h, w = -(-H // k), -(-W // k)
    pad = np.zeros((h * k, w * k, 4), np.uint8); pad[:H, :W] = a
    blocks = pad.reshape(h, k, w, k, 4).transpose(0, 2, 1, 3, 4).reshape(h, w, k * k, 4)
    out = np.zeros((h, w, 4), np.uint8)
    for y in range(h):
        for x in range(w):
            b = blocks[y, x]; op = b[b[:, 3] > 0]
            if len(op) * 2 < k * k: continue
            cols, cnt = np.unique(op[:, :3], axis=0, return_counts=True)
            out[y, x, :3] = cols[cnt.argmax()]; out[y, x, 3] = 255
    return Image.fromarray(out)

def mark_loader_blocks(new, orig, block=16):
    """The LSS Mod Loader lays a mod image over the original and only wipes the
    16x16 blocks where the mod has visible pixels. Anywhere the new sheet is fully
    see-through but the original wasn't, the old art would show through (Bowser's
    spikes peeking over the boss's head). Put one almost-invisible pixel (alpha 1)
    in each of those blocks so the loader wipes them too."""
    a = np.array(new).copy(); o = np.array(orig)
    H, W = min(a.shape[0], o.shape[0]), min(a.shape[1], o.shape[1])
    for by in range(0, H, block):
        for bx in range(0, W, block):
            nb = a[by:by + block, bx:bx + block, 3]
            ob = o[by:by + block, bx:bx + block, 3]
            if not nb.any() and ob.any():
                a[by, bx] = (0, 0, 0, 1)
    return Image.fromarray(a)

def whole_k(s, src=None, w=None, h=None):
    """Smallest whole-number shrink that is at least as small as scale s (and fits w x h)."""
    k = max(1, int(np.ceil(1 / s - 1e-6))) if s < 1 else 1
    if src is not None:
        while (w and -(-src.width // k) > w) or (h and -(-src.height // k) > h): k += 1
    return k

# ---------------------------------------------------------------- frame map
B0 = "images/bowser-sheet0.webp"; B1 = "images/bowser-sheet1.webp"
BI0 = "images/buttonicons-sheet0.webp"; BI1 = "images/buttonicons-sheet1.webp"
SH9 = "images/shared-9-sheet1.webp"
# (sheet, x, y) of each Bowser frame -> (pose, style, effects)
FRAME_MAP = {
    # SMW-style Bowser (style 2, ~58px tall)
    (B0, 289, 321): ("idle1", 2, []), (B0, 289, 257): ("idle2", 2, []),
    (B0, 460, 321): ("idle2", 2, ["flip"]), (B0, 1, 385): ("idle1", 2, ["flip"]),
    (B0, 347, 193): ("idle2", 2, []), (B0, 346, 321): ("idle1", 2, ["bob"]), (B0, 1, 257): ("idle2", 2, ["bob"]),
    (B0, 347, 257): ("attack1", 2, []), (B0, 405, 257): ("attack1", 2, []), (B0, 115, 257): ("attack2", 2, []),
    (B0, 385, 1): ("special", 2, []), (B0, 1, 129): ("special", 2, []), (B0, 63, 129): ("special", 2, []),
    (BI0, 129, 385): ("special", 2, []), (B0, 173, 257): ("special", 2, []),
    (B0, 385, 449): ("attack1", 2, []), (B0, 65, 449): ("attack1", 2, []), (B0, 229, 321): ("attack1", 2, []),
    (B0, 449, 1): ("attack2", 2, []), (B0, 185, 129): ("attack2", 2, []), (B0, 237, 129): ("attack2", 2, []),
    (B0, 321, 1): ("attack2", 2, []), (B0, 65, 1): ("attack2", 2, []),
    (B0, 173, 321): ("idle1", 2, ["squash"]), (B0, 125, 193): ("idle2", 2, []),
    (B0, 116, 321): ("idle1", 2, ["squash"]), (B0, 403, 321): ("idle2", 2, ["flip"]), (B0, 65, 385): ("idle1", 2, ["flip"]),
    (B0, 129, 1): ("idle1", 2, ["rot90"]), (B0, 251, 1): ("idle1", 2, ["rot270"]),
    (B0, 231, 257): ("attack1", 2, []), (B0, 1, 321): ("attack2", 2, []),
    (B0, 483, 449): ("idle1", 2, ["morph"]), (B0, 59, 321): ("idle1", 2, ["morph"]), (B0, 116, 449): ("idle1", 2, ["morph"]),
    (B0, 58, 257): ("idle1", 2, ["morph"]), (B0, 289, 193): ("idle1", 2, ["morph"]), (B0, 449, 193): ("idle1", 2, ["morph"]),
    (B0, 481, 129): ("idle1", 2, ["peek"]), (B0, 281, 449): ("idle1", 2, ["peek"]), (B1, 0, 0): ("idle1", 2, ["peek"]),
    (SH9, 257, 897): ("attack1", 2, []),
    # SMB1-style Bowser (style 1, ~34px tall)
    (B0, 1, 449): ("idle1", 1, []), (B0, 315, 449): ("idle2", 1, []),
    (B0, 417, 193): ("idle2", 1, ["flip"]), (B0, 483, 385): ("idle1", 1, ["flip"]),
    (B0, 349, 449): ("idle2", 1, ["bob"]), (B0, 449, 449): ("idle1", 1, ["bob"]),
    (B0, 193, 385): ("attack1", 1, []), (B0, 257, 385): ("attack2", 1, []),
    (B0, 193, 449): ("attack1", 1, []), (B0, 449, 385): ("attack1", 1, []),
    (B0, 463, 257): ("attack2", 1, []), (B0, 129, 385): ("attack2", 1, []),
    (B0, 321, 385): ("idle1", 1, ["squash"]), (B0, 385, 385): ("idle2", 1, ["flip"]),
    (BI1, 16, 1): ("idle1", 1, ["rot90"]), (B0, 225, 481): ("idle1", 1, ["rot270"]),
    (B0, 169, 481): ("idle1", 1, ["rot90", "vflip"]),
}
# Same mapping keyed by Bowser's animation name + frame number, so the build still
# works if a newer SMC version moves frames around on the sprite sheets.
NAME_MAP = {
    ("1Idle", 0): ("idle1", 1, []),
    ("1Idle", 1): ("idle2", 1, []),
    ("1Turn", 0): ("idle2", 1, ['flip']),
    ("1Turn", 1): ("idle1", 1, ['flip']),
    ("1Walk", 0): ("idle2", 1, ['bob']),
    ("1Walk", 1): ("idle1", 1, []),
    ("1Walk", 2): ("idle1", 1, ['bob']),
    ("1Walk", 3): ("idle1", 1, []),
    ("1PrepareFire", 0): ("attack1", 1, []),
    ("1SpewFire", 0): ("attack2", 1, []),
    ("1GrabWand", 0): ("attack1", 1, []),
    ("1PrepareWand", 0): ("attack1", 1, []),
    ("1UseWand", 0): ("attack2", 1, []),
    ("1UseWand", 1): ("attack2", 1, []),
    ("1PutWandBack", 0): ("attack1", 1, []),
    ("1PutWandBack", 1): ("attack1", 1, []),
    ("1Jumping", 0): ("idle2", 1, ['bob']),
    ("1Hit", 0): ("idle1", 1, ['squash']),
    ("1Hit", 1): ("idle2", 1, ['flip']),
    ("1ShellDash", 0): ("idle1", 1, ['rot90']),
    ("1ShellDash", 1): ("idle1", 1, ['rot270']),
    ("1ShellDash", 2): ("idle1", 1, ['rot90', 'vflip']),
    ("1ShellDash", 3): ("idle1", 1, ['rot270']),
    ("2Idle", 0): ("idle1", 2, []),
    ("2Idle", 1): ("idle2", 2, []),
    ("2Turn", 0): ("idle2", 2, ['flip']),
    ("2Turn", 1): ("idle1", 2, ['flip']),
    ("2WalkL", 0): ("idle2", 2, []),
    ("2WalkL", 1): ("idle1", 2, ['bob']),
    ("2WalkL", 2): ("idle2", 2, ['bob']),
    ("2WalkL", 3): ("idle1", 2, []),
    ("2WalkL", 4): ("idle1", 2, []),
    ("2WalkR", 0): ("idle2", 2, ['bob']),
    ("2WalkR", 1): ("idle1", 2, ['bob']),
    ("2WalkR", 2): ("idle2", 2, []),
    ("2WalkR", 3): ("idle1", 2, []),
    ("2WalkR", 4): ("idle1", 2, []),
    ("2PrepareFire", 0): ("idle2", 2, []),
    ("2PrepareFire", 1): ("attack1", 2, []),
    ("2PrepareFire", 2): ("attack1", 2, []),
    ("2SpewFire", 0): ("attack2", 2, []),
    ("2PrepareHammer", 0): ("special", 2, []),
    ("2PrepareHammer", 1): ("special", 2, []),
    ("2PrepareHammer", 2): ("special", 2, []),
    ("2SwingHammer", 0): ("special", 2, []),
    ("2ReleaseHammer", 0): ("special", 2, []),
    ("2GrabWand", 0): ("attack1", 2, []),
    ("2GrabWand", 1): ("attack1", 2, []),
    ("2PrepareWand", 0): ("attack1", 2, []),
    ("2PrepareWand", 1): ("attack2", 2, []),
    ("2PrepareWand", 2): ("attack2", 2, []),
    ("2PrepareWand", 3): ("attack2", 2, []),
    ("2UseWand", 0): ("attack2", 2, []),
    ("2UseWand", 1): ("attack2", 2, []),
    ("2PutWandBack", 0): ("attack1", 2, []),
    ("2PutWandBack", 1): ("attack1", 2, []),
    ("2PutWandBack", 2): ("attack1", 2, []),
    ("2PrepareJump", 0): ("idle2", 2, []),
    ("2PrepareJump", 1): ("idle1", 2, ['squash']),
    ("2Jumping", 0): ("idle2", 2, []),
    ("2Landed", 0): ("idle1", 2, ['squash']),
    ("2Landed", 1): ("idle2", 2, []),
    ("2Hit", 0): ("idle1", 2, ['squash']),
    ("2Hit", 1): ("idle2", 2, ['flip']),
    ("2Hit", 2): ("idle1", 2, ['flip']),
    ("2Defeated", 0): ("idle1", 2, ['rot90']),
    ("2Defeated", 1): ("idle1", 2, ['rot270']),
    ("2PeachDisguise3", 0): ("idle1", 2, ['morph']),
    ("2PeachDisguise3", 1): ("idle1", 2, ['morph']),
    ("2PeachDisguise3", 2): ("idle1", 2, ['morph']),
    ("2PeachDisguise3", 3): ("idle1", 2, ['morph']),
    ("2PeachDisguise3", 4): ("idle1", 2, ['morph']),
    ("2PeachDisguise3", 5): ("idle1", 2, ['morph']),
    ("2PeachDisguise3", 6): ("idle2", 2, []),
    ("2PeachDisguise3", 7): ("attack1", 2, []),
    ("2PeachDisguise3", 8): ("attack2", 2, []),
    ("2LookOutVehicle", 0): ("idle1", 2, ['peek']),
    ("2LookOutVehicle", 1): ("idle1", 2, ['peek']),
    ("2LookOutVehicle", 2): ("idle1", 2, ['peek']),
    ("2JumpOutVehicle", 0): ("attack1", 2, []),
}

def guess_spec(anim, i):
    """For Bowser animations this script hasn't seen (newer SMC versions)."""
    n = anim.lower(); style = 1 if anim.startswith("1") else 2
    if "peach" in n: return None
    if "fire" in n or "spew" in n: return ("attack2" if i else "attack1", style, [])
    if "wand" in n or "magic" in n: return ("attack2" if i else "attack1", style, [])
    if "hammer" in n: return ("special", style, [])
    if "hit" in n: return ("idle1", style, ["squash"])
    if "defeat" in n: return ("idle1", style, ["rot90" if i % 2 == 0 else "rot270"])
    if "vehicle" in n: return ("idle1", style, ["peek"])
    return ("idle2" if i % 2 else "idle1", style, [])

TARGET_H = {2: 58, 1: 34}

def load_poses(boss_dir):
    files = {p: os.path.join(boss_dir, p + ".png") for p in POSES}
    sheet = os.path.join(boss_dir, "sheet.png")
    poses = {}
    if os.path.exists(sheet):
        for p, part in zip(POSES, split_sheet(Image.open(sheet))):
            try: poses[p] = clean(part)
            except ValueError: pass
    for p, f in files.items():
        if os.path.exists(f):
            poses[p] = clean(Image.open(f))
    if "idle1" not in poses:
        raise SystemExit("No idle1 pose found. Add boss/idle1.png or boss/sheet.png")
    for p in POSES:
        if p not in poses:
            poses[p] = poses[FALLBACK[p]]
            print(f"  {p}: missing, using {FALLBACK[p]}")
    return poses

ICONS = {
    # editor attack-picker icons + editor object icon (sheet, x, y, w, h, rotated, pose, keep_box)
    "fire": (BI0, 65, 385, 70, 60, True, "attack2", (0, 0, 22, 60)),   # keep the fireball on the left
    "wand": (BI0, 1, 259, 73, 60, True, "attack1", (0, 0, 24, 30)),    # keep the magic symbols
}
FRAMED_ICON = ("images/framededitorobjecticons-sheet0.webp", 239, 193, 32, 32)

def render_frame(src_pose, s, fx, w, h, ox, oy, ref, morph_color=None):
    src = src_pose
    if "rot90" in fx: src = src.rotate(90, expand=True)
    if "rot270" in fx: src = src.rotate(-90, expand=True)
    if "squash" in fx: src = src.resize((src.width, max(1, round(src.height * 0.88))), Image.NEAREST)
    if morph_color is not None:
        if "peek" not in fx: s = min(s, w / src.width * 0.999, h / src.height * 0.999)
        spr = src if abs(s - 1) < 1e-6 else pixel_down(src, s)
    elif "peek" in fx:
        spr = block_down(src, whole_k(s))
    else:
        spr = block_down(src, whole_k(s, src, w, h))
    if "peek" in fx: spr = spr.crop((0, 0, spr.width, min(h, spr.height)))
    if spr.width > w:
        l = (spr.width - w) // 2; spr = spr.crop((l, 0, l + w, spr.height))
    if "flip" in fx: spr = spr.transpose(Image.FLIP_LEFT_RIGHT)
    if "vflip" in fx: spr = spr.transpose(Image.FLIP_TOP_BOTTOM)
    if morph_color is not None:
        sa = np.array(spr); sa[sa[..., 3] > 0, :3] = morph_color; spr = Image.fromarray(sa)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bottom = min(h, round(oy * h) + 1) - (1 if "bob" in fx else 0)
    left = max(0, min(w - spr.width, round(ox * w - spr.width / 2)))
    canvas.alpha_composite(spr, (left, max(0, bottom - spr.height)))
    return canvas

class Shelf:
    """Packs new frames into the empty space added to the sheet."""
    def __init__(self, W, top_band):
        self.W, self.x, self.y, self.row_h, self.top_band = W, 0, 0, 0, top_band
    def place(self, w, h):
        # first fill the band to the right of the original 512x512, then below it
        x0 = 514 if self.y < self.top_band else 0
        if self.x < x0: self.x = x0
        if self.x + w > self.W:
            self.x = x0; self.y += self.row_h + 2; self.row_h = 0
            if self.y < self.top_band: self.x = 514
            else: self.x = 0
            if self.y < self.top_band and self.y + h > self.top_band:
                self.y = self.top_band + 2; self.x = 0
        pos = (self.x, self.y)
        self.x += w + 2; self.row_h = max(self.row_h, h)
        return pos

EXTRA_OBJECTS = {  # other objects that show Bowser: object name -> animation names
    "ButtonIcons": ("BWAttack0", "BWAttack1", "BWAttack2", "BWAttack3"),
    "FramedEditorObjectIcons": ("1_bs2", "2_bs2"),
    "EditorObjects": ("1_bs2", "2_bs2"),
    "Bowser_Dummy": None,
}

def _frames(project, obj, anims=None):
    for t in project[3]:
        if isinstance(t, list) and t and t[0] == obj and len(t) > 7 and isinstance(t[7], list):
            for a in t[7]:
                if anims is None or a[0] in anims:
                    for i, fr in enumerate(a[7]):
                        yield a[0], i, fr

def needed_images(project):
    """Every sprite sheet that holds a Bowser picture in this game version."""
    paths = {fr[0] for _, _, fr in _frames(project, "Bowser")}
    for obj, anims in EXTRA_OBJECTS.items():
        paths |= {fr[0] for _, _, fr in _frames(project, obj, anims)}
    return sorted(p for p in paths if p.startswith("images/"))

def build(game, boss_dir, mode="classic"):
    poses = load_poses(boss_dir)
    ref = max(im.height for im in poses.values())
    data_path = os.path.join(game, "data.json")
    root = json.load(open(data_path, encoding="utf-8"))
    d = root["project"]
    bowser = [o for o in d[3] if isinstance(o, list) and o and o[0] == "Bowser"][0]
    rects = {(fr[0], fr[2], fr[3]): fr for a in bowser[7] for fr in a[7]}
    avoid = set()
    pal_path = os.path.join(game, "Palettes", "Misc_Palettes.json")
    if os.path.exists(pal_path):
        pal = json.load(open(pal_path, encoding="utf-8"))["data"]
        avoid = {tuple(int(v) for v in c.split(",")) for k in ("1_Bowser", "2_Bowser") if k in pal
                 for c in pal[k].split("--")[0].split("|")}
    sheets = {}
    def sheet(p):
        if p not in sheets:
            sheets[p] = Image.open(os.path.join(game, p)).convert("RGBA")
        return sheets[p]
    def dodge(canvas):   # keep Bowser's palette-swap feature from recoloring the art
        ca = np.array(canvas)
        for c in avoid:
            m = (ca[..., 0] == c[0]) & (ca[..., 1] == c[1]) & (ca[..., 2] == c[2]) & (ca[..., 3] > 0)
            ca[m, 2] = np.where(ca[m, 2] < 255, ca[m, 2] + 1, 254)
        return Image.fromarray(ca)
    def paste(path, x, y, canvas, rot):
        if rot: canvas = canvas.rotate(-90, expand=True)
        sh = sheet(path)
        sh.paste(Image.new("RGBA", canvas.size, (0, 0, 0, 0)), (x, y)); sh.paste(canvas, (x, y))

    # "sharp": SMW-style boss uses the art at 1:1 (or an exact 1/2, 1/3... for huge art)
    k = max(1, -(-ref // 100))
    s_big = 1.0 / k
    F = (ref * s_big) / TARGET_H[2] if mode == "sharp" else 1.0
    big_frames = []; new_rects = {}

    # one spec per unique sheet rectangle used by Bowser
    jobs = {}
    for a in bowser[7]:
        for i, fr in enumerate(a[7]):
            key = (fr[0], fr[2], fr[3])
            spec = NAME_MAP.get((a[0], i)) or FRAME_MAP.get(key)
            if spec is None:
                spec = guess_spec(a[0], i)
                if spec: print(f"  note: new animation {a[0]} frame {i}, using {spec[0]}")
            if spec and key not in jobs:
                jobs[key] = (spec, fr)
    count = 0
    for key, ((pose, style, fx), fr) in jobs.items():
        path, _, x, y, w, h, rot, _, ox, oy = fr[:10]
        morph_color = None
        if "morph" in fx:   # Peach-disguise transformation silhouettes keep their color
            orig = np.array(sheet(path).crop((x, y, x + (h if rot else w), y + (w if rot else h))))
            px = orig[orig[..., 3] > 0][:, :3]
            if len(px):
                cols, cnt = np.unique(px, axis=0, return_counts=True)
                if len(cols) <= 4: morph_color = cols[cnt.argmax()]
        # small version in the original slot (used by the editor preview, SMB1 style, shared icons)
        s_small = (h - 1) / ref if "morph" in fx else TARGET_H[style] / ref
        paste(path, x, y, dodge(render_frame(poses[pose], s_small, fx, w, h, ox, oy, ref, morph_color)), rot)
        count += 1
        # big, crisp version on new space; Bowser's own frames get pointed at it
        if style == 2 and F > 1.0 and "peek" not in fx:
            W2, H2 = int(np.ceil(w * F)), int(np.ceil(h * F))
            if "morph" not in fx:   # grow the frame if needed so the art never has to shrink
                src = poses[pose]
                if "rot90" in fx or "rot270" in fx: sw, sh_ = src.height, src.width
                else: sw, sh_ = src.width, src.height
                if "squash" in fx: sh_ = round(sh_ * 0.88)
                W2 = max(W2, -(-sw // k) + 2); H2 = max(H2, -(-sh_ // k) + 2)
            s_here = ((h - 1) / ref) * F if "morph" in fx else s_big
            if "morph" in fx and morph_color is None: s_here = min(s_big, s_here)
            canvas = dodge(render_frame(poses[pose], s_here, fx, W2, H2, ox, oy, ref, morph_color))
            big_frames.append((key, canvas))

    # editor attack icons + framed editor icon
    def find_frame(obj, anim):
        o = [t for t in d[3] if isinstance(t, list) and t and t[0] == obj]
        for a in (o[0][7] if o else []):
            if a[0] == anim and a[7]: return a[7][0]
        return None
    # pack the big frames below the original art on the sheet that holds most of Bowser
    BIG = None
    if big_frames:
        counts = {}
        for (path, _, _), _c in big_frames: counts[path] = counts.get(path, 0) + 1
        BIG = max(counts, key=counts.get)
        base = sheet(BIG); Wb, Hb = base.size
        W = max(Wb, max(c.width for _, c in big_frames) + 2)
        x, y, row = 0, Hb + 2, 0
        for key, c in big_frames:
            if x + c.width > W: x, y, row = 0, y + row + 2, 0
            new_rects[key] = (x, y, c.width, c.height); x += c.width + 2; row = max(row, c.height)
        Hn = y + row + 2
        pot = lambda v: 1 << (int(v) - 1).bit_length()   # keep sheets power-of-two like the originals
        Hn = pot(Hn); W = pot(W)
        big = Image.new("RGBA", (W, Hn), (0, 0, 0, 0)); big.paste(base, (0, 0))
        for key, c in big_frames:
            nx, ny, _, _ = new_rects[key]; big.paste(c, (nx, ny))
        sheets[BIG] = big

    # editor previews of Bowser that live in their own spots
    for an, i, fr in _frames(d, "EditorObjects", EXTRA_OBJECTS["EditorObjects"]):
        key = (fr[0], fr[2], fr[3])
        if key in jobs: continue
        path, _, x, y, w, h, rot, _, ox, oy = fr[:10]
        st = 1 if an.startswith("1") else 2
        paste(path, x, y, dodge(render_frame(poses["idle1"], min(TARGET_H[st] / ref, (h - 1) / ref), [], w, h, ox, oy, ref)), rot)

    # attack-picker icons in the editor: keep the attack effect, swap Bowser for the boss
    icon_pose = {"BWAttack0": "attack2", "BWAttack1": "special", "BWAttack2": "attack1", "BWAttack3": "idle1"}
    ib = [t for t in d[3] if isinstance(t, list) and t and t[0] == "ButtonIcons"]
    for an in (ib[0][7] if ib else []):
        if an[0] not in icon_pose: continue
        for fr in an[7]:
            key = (fr[0], fr[2], fr[3])
            if key in jobs: continue   # already a real Bowser frame
            path, x, y, w, h, rot = fr[0], fr[2], fr[3], fr[4], fr[5], fr[6]
            sh = sheet(path)
            orig = sh.crop((x, y, x + (h if rot else w), y + (w if rot else h)))
            if rot: orig = orig.rotate(90, expand=True)
            ka = np.array(orig)
            rgb = ka[..., :3].astype(int); op = ka[..., 3] > 0
            keep = np.zeros(op.shape, bool)
            if an[0] == "BWAttack0":   # keep just the fireball (its colors + outline) on the left
                fire = np.zeros(op.shape, bool)
                for c in [(248, 192, 0), (248, 120, 0), (184, 40, 0), (255, 251, 255), (248, 248, 248)]:
                    fire |= (np.abs(rgb - c).sum(-1) == 0) & op
                black = (rgb.sum(-1) == 0) & op
                near = np.zeros_like(fire)
                near[1:] |= fire[:-1]; near[:-1] |= fire[1:]; near[:, 1:] |= fire[:, :-1]; near[:, :-1] |= fire[:, 1:]
                keep = (fire | (black & near)); keep[:, w // 2:] = False
                kl, ks = _label(keep)
                for n, sz in enumerate(ks, start=1):
                    if sz < 6: keep[kl == n] = False
            ka[~keep] = 0
            kept = Image.fromarray(ka)
            # portrait at the game's own pixel size: 1:1 for big icons, exactly 1/2 for small ones
            k = 1 if h >= 48 else 2
            spr = block_down(poses[icon_pose[an[0]]], k)
            room = w - (w // 3 if an[0] == "BWAttack0" else 0)
            if spr.width > room:
                l = (spr.width - room) // 2; spr = spr.crop((l, 0, l + room, spr.height))
            spr = spr.crop((0, 0, spr.width, min(h, spr.height)))
            kept.alpha_composite(spr, (w - spr.width, 0))
            paste(path, x, y, dodge(kept), rot)
    for _an, _i, ffr in _frames(d, "FramedEditorObjectIcons", ("1_bs2", "2_bs2")):   # toolbar icons, every frame
        if ffr[6]: continue
        fp, fx_, fy, fw, fh = ffr[0], ffr[2], ffr[3], ffr[4], ffr[5]
        idle = poses["idle1"]
        head = block_down(idle, 1 if fw >= 28 else 2)
        cx = head.width // 2
        head = head.crop((max(0, cx - fw // 2), 0, max(0, cx - fw // 2) + min(fw, head.width), min(fh, head.height)))
        icon = Image.new("RGBA", (fw, fh), (0, 0, 0, 0)); icon.alpha_composite(head, ((fw - head.width) // 2, 0))
        sheet(fp).paste(Image.new("RGBA", (fw, fh), (0, 0, 0, 0)), (fx_, fy)); sheet(fp).paste(dodge(icon), (fx_, fy))

    for p, im in sheets.items():
        orig = Image.open(os.path.join(game, p)).convert("RGBA")
        im = mark_loader_blocks(im, orig)
        im.save(os.path.join(game, p), "WEBP", lossless=True, quality=100, method=6)

    if new_rects:
        size = os.path.getsize(os.path.join(game, BIG))
        for a in bowser[7]:
            for fr in a[7]:
                key = (fr[0], fr[2], fr[3])
                if key in new_rects:
                    nx, ny, W2, H2 = new_rects[key]
                    fr[0] = BIG; fr[2], fr[3], fr[4], fr[5], fr[6] = nx, ny, W2, H2, False
        def fix_sizes(o):
            if isinstance(o, list):
                if len(o) > 1 and o[0] == BIG and isinstance(o[1], int): o[1] = size
                for v in o: fix_sizes(v)
        fix_sizes(d)
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(root, f, separators=(",", ":"), ensure_ascii=False)
        print(f"  sharp mode: boss is {round(ref * s_big)}px tall at {'1:1' if k == 1 else '1:' + str(k)} ({len(new_rects)} big frames)")

    off = os.path.join(game, "offline.json")
    if os.path.exists(off):
        o = json.load(open(off, encoding="utf-8")); o["version"] = int(time.time() * 1000)
        json.dump(o, open(off, "w", encoding="utf-8"), indent=4)
    print(f"Boss built: {count} frames replaced in {len(sheets)} sheets.")

if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(__doc__)
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "classic")
