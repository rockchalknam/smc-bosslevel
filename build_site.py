#!/usr/bin/env python3
"""
Boss Picker site builder: one hosted copy of Super Mario Construct where every
student's boss runs at full size, picked with a link like  .../?boss=mr-n

    python tools/build_site.py turned-in site

  turned-in/  one zip (or folder) of poses per student, named with their code name
  site/       the website folder. Publish it with GitHub Pages.

What it does each run:
  1. Makes sure site/ holds the same game version LSS is running (downloads it
     the first time, and again whenever LSS updates).
  2. Adds the Boss Picker pieces (service worker, picker page).
  3. Builds every boss in turned-in/ into site/bosses/<code>/ at full size.
     Each boss keeps a copy of its poses, so after a game update every boss is
     rebuilt automatically.
"""
import os, sys, json, shutil, tempfile, zipfile, re, subprocess, urllib.request, urllib.parse, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_boss
from make_modpacks import student_dirs

BASE_URL = os.environ.get("SMC_BASE_URL", "https://levelsharesquare.com/html5/supermarioconstruct/")
EXTRA_FILES = ["index.html", "offline.json", "appmanifest.json", "data.json", "style.css", "extra.css",
               "scripts/offlineclient.js", "scripts/main.js", "scripts/register-sw.js",
               "scripts/modernjscheck.js", "scripts/supportcheck.js"]
POSES = ["idle1", "idle2", "attack1", "attack2", "special"]

# Teacher bosses: listed first in the Boss Picker, right after Normal Bowser, in this order.
FEATURED = ["mr-n"]

def fetch_bytes(path, tries=4):
    url = BASE_URL + urllib.parse.quote(path)
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:
            last = e
            try:
                return subprocess.run(["curl", "-fsSL", "-A", "Mozilla/5.0", url], check=True, capture_output=True).stdout
            except Exception as e2:
                last = e2
            time.sleep(1 + attempt)
    raise RuntimeError(f"couldn't download {path}: {last}")

def save(site, path, data):
    dst = os.path.join(site, path)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as w: w.write(data)

def ensure_game(site):
    """Download the full game from LSS if site/ is missing or out of date. Returns True if (re)downloaded."""
    remote = json.loads(fetch_bytes("offline.json").decode("utf-8"))
    local_path = os.path.join(site, "offline.json")
    if os.path.exists(local_path) and os.path.exists(os.path.join(site, "scripts", "main.js")):
        local = json.load(open(local_path, encoding="utf-8"))
        if local.get("version") == remote.get("version"):
            print("Game files are up to date.")
            return False
    files = sorted(set(remote.get("fileList", []) + EXTRA_FILES))
    files = [f for f in files if f and not f.endswith("/") and f != "sw.js"]
    print(f"Downloading the game from LSS ({len(files)} files, about 75 MB). This takes a few minutes the first time...")
    done = [0]
    def job(f):
        save(site, f, fetch_bytes(f)); done[0] += 1
        if done[0] % 50 == 0: print(f"  {done[0]}/{len(files)}")
    with ThreadPoolExecutor(max_workers=12) as ex:
        list(ex.map(job, files))
    # level music loads on demand, so it isn't in the file list: find it by number
    extra = []
    for theme, prefix in (("Themes/Music_SMW.json", "media/SMW/Music2_"), ("Themes/Music_SMAS1.json", "media/SMAS1/Music1_")):
        try: n = json.load(open(os.path.join(site, theme), encoding="utf-8"))["size"][0]
        except Exception: n = 60
        extra += [f"{prefix}{i}.webm" for i in range(1, n + 4)]
    def probe(f):
        try: save(site, f, fetch_bytes(f, tries=1)); return 1
        except Exception: return 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        got = sum(ex.map(probe, extra))
    print(f"  plus {got} music tracks")
    save(site, "offline.json", json.dumps(remote, indent=4).encode("utf-8"))
    print("Game downloaded.")
    return True

def add_picker(site):
    for f in ("sw.js", "boss-boot.js", "bosses.html"):
        shutil.copy(os.path.join(HERE, "site", f), os.path.join(site, f))
    open(os.path.join(site, ".nojekyll"), "w").close()
    idx = os.path.join(site, "index.html")
    html = open(idx, encoding="utf-8").read()
    if "boss-boot.js" not in html:
        for s in ("scripts/offlineclient.js", "scripts/main.js", "scripts/register-sw.js"):
            html = re.sub(r'\s*<script src="' + re.escape(s) + r'" type="module"></script>', "", html)
        html = html.replace('<script src="scripts/supportcheck.js"></script>',
                            '<script src="scripts/supportcheck.js"></script>\n\t<script src="boss-boot.js"></script>')
        if "boss-boot.js" not in html:
            raise SystemExit("Couldn't find where to add the Boss Picker in index.html. Send this error to Claude.")
        open(idx, "w", encoding="utf-8").write(html)

def build_one(site, code, pose_dir, tmp):
    d = json.load(open(os.path.join(site, "data.json"), encoding="utf-8"))["project"]
    game = os.path.join(tmp, "g-" + code)
    if os.path.exists(game): shutil.rmtree(game)
    os.makedirs(os.path.join(game, "Palettes"))
    shutil.copy(os.path.join(site, "data.json"), game)
    pal = os.path.join(site, "Palettes", "Misc_Palettes.json")
    if os.path.exists(pal): shutil.copy(pal, os.path.join(game, "Palettes"))
    for rel in build_boss.needed_images(d):
        os.makedirs(os.path.dirname(os.path.join(game, rel)), exist_ok=True)
        shutil.copy(os.path.join(site, rel), os.path.join(game, rel))
    build_boss.build(game, pose_dir, "sharp")
    out = os.path.join(site, "bosses", code)
    if os.path.exists(os.path.join(out, "images")): shutil.rmtree(os.path.join(out, "images"))
    images = []
    for rel in build_boss.needed_images(d):
        new_b = open(os.path.join(game, rel), "rb").read()
        if new_b != open(os.path.join(site, rel), "rb").read():
            save(out, rel, new_b); images.append(rel)
    nd = json.load(open(os.path.join(game, "data.json"), encoding="utf-8"))["project"]
    bowser = [t for t in nd[3] if isinstance(t, list) and t and t[0] == "Bowser"][0]
    frames = {a[0]: a[7] for a in bowser[7]}
    info = {"code": code, "gameVersion": d[16], "images": images, "bowserFrames": frames}
    json.dump(info, open(os.path.join(out, "boss.json"), "w", encoding="utf-8"), separators=(",", ":"))
    # thumbnail for the picker + keep the poses so the boss can be rebuilt after game updates
    poses = build_boss.load_poses(pose_dir)
    poses["idle1"].save(os.path.join(out, "thumb.png"))
    src = os.path.join(out, "src"); os.makedirs(src, exist_ok=True)
    for p in POSES:
        f = os.path.join(pose_dir, p + ".png")
        if os.path.exists(f) and os.path.abspath(f) != os.path.abspath(os.path.join(src, p + ".png")):
            shutil.copy(f, os.path.join(src, p + ".png"))
    sheet = os.path.join(pose_dir, "sheet.png")
    if os.path.exists(sheet) and os.path.abspath(sheet) != os.path.abspath(os.path.join(src, "sheet.png")):
        shutil.copy(sheet, os.path.join(src, "sheet.png"))

def main(src, site):
    os.makedirs(site, exist_ok=True)
    updated = ensure_game(site)
    add_picker(site)
    version = json.load(open(os.path.join(site, "data.json"), encoding="utf-8"))["project"][16]
    bosses_dir = os.path.join(site, "bosses"); os.makedirs(bosses_dir, exist_ok=True)
    ok, failed = [], []
    with tempfile.TemporaryDirectory() as tmp:
        todo = {}
        # bosses already on the site that need a rebuild for a new game version
        for code in sorted(os.listdir(bosses_dir)):
            info_p = os.path.join(bosses_dir, code, "boss.json")
            if os.path.isdir(os.path.join(bosses_dir, code, "src")) and os.path.exists(info_p):
                if json.load(open(info_p, encoding="utf-8")).get("gameVersion") != version:
                    todo[code] = os.path.join(bosses_dir, code, "src")
        # new or updated turned-in bosses
        if os.path.isdir(src):
            for code, d in student_dirs(src, tmp):
                todo[code] = d
        for code, d in todo.items():
            print(f"\n== {code}")
            try:
                build_one(site, code, d, tmp); ok.append(code)
            except SystemExit as e:
                print("  skipped:", e); failed.append((code, str(e)))
            except Exception as e:
                print("  FAILED:", e); failed.append((code, repr(e)))
    codes = sorted((c for c in os.listdir(bosses_dir) if os.path.exists(os.path.join(bosses_dir, c, "boss.json"))),
                   key=lambda c: (FEATURED.index(c) if c in FEATURED else len(FEATURED), c))
    def period_of(code):
        m = re.search(r"-p([1-9])$", code)
        return int(m.group(1)) if m else None
    json.dump({"gameVersion": version, "bosses": [{"code": c, "period": period_of(c)} for c in codes]},
              open(os.path.join(bosses_dir, "index.json"), "w", encoding="utf-8"), indent=1)
    print(f"\nSite ready for {version}: {len(codes)} bosses ({len(ok)} built this run).")
    for c, why in failed: print(f"  needs a fix: {c}: {why}")
    if not os.environ.get("GITHUB_ACTIONS"): print("Next: in GitHub Desktop, commit and push the site folder.")

if __name__ == "__main__":
    if len(sys.argv) != 3: raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
