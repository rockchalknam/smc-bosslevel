#!/usr/bin/env python3
"""
Turn every student's Boss Maker download into a ready-to-load LSS mod loader modpack.

    python tools/fetch_base.py                         # once per game update
    python tools/make_modpacks.py base turned-in modpacks

  base/       game files from fetch_base.py
  turned-in/  one zip (or folder) per student, named with their code name,
              e.g. dragonqueen.zip -> modpack "VRMS-dragonqueen"
  modpacks/   output: one folder + one .zip per student

Each modpack holds loader.json and images/ (the swapped sprite sheets).
The boss fits Bowser's own frames, shrunk only by whole numbers so pixels
stay hard-edged. Art drawn about 56 px tall shows at exactly 1:1.
("sharp" as a 4th argument also writes data.json for full-size frames, but the
LSS Mod Loader can't deliver a file that big, so only use it on a self-hosted copy.)
"""
import os, sys, json, time, shutil, zipfile, tempfile, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_boss

PREFIX = "VRMS"
BASE_URL = "https://levelsharesquare.com/html5/supermarioconstruct/"

def student_dirs(src, tmp):
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        code = re.sub(r"[^a-z0-9-]+", "-", os.path.splitext(name)[0].lower()).strip("-")
        if not code: continue
        if name.lower().endswith(".zip"):
            d = os.path.join(tmp, "in", code); os.makedirs(d, exist_ok=True)
            with zipfile.ZipFile(path) as z:
                for m in z.namelist():
                    base = os.path.basename(m)
                    if base.lower().endswith(".png") and not base.startswith("."):
                        with z.open(m) as r, open(os.path.join(d, base.lower()), "wb") as w: w.write(r.read())
            yield code, d
        elif os.path.isdir(path):
            yield code, path

def main(base, src, out, mode="classic"):
    os.makedirs(out, exist_ok=True)
    game_ver = json.load(open(os.path.join(base, "data.json"), encoding="utf-8"))["project"][16]
    orig_data = open(os.path.join(base, "data.json"), "rb").read()
    ok, failed = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for code, boss_dir in student_dirs(src, tmp):
            print(f"\n== {code}")
            game = os.path.join(tmp, "game", code)
            shutil.copytree(base, game)
            try:
                build_boss.build(game, boss_dir, mode)
            except SystemExit as e:
                print("  skipped:", e); failed.append((code, str(e))); continue
            except Exception as e:
                print("  FAILED:", e); failed.append((code, repr(e))); continue
            name = f"{PREFIX}-{code}"
            pack = os.path.join(out, name)
            if os.path.exists(pack): shutil.rmtree(pack)
            os.makedirs(os.path.join(pack, "images"))
            for f in os.listdir(os.path.join(game, "images")):   # only the sheets that changed
                new_b = open(os.path.join(game, "images", f), "rb").read()
                if new_b != open(os.path.join(base, "images", f), "rb").read():
                    open(os.path.join(pack, "images", f), "wb").write(new_b)
            root = {"images": ["images/", "img"]}
            new_data = open(os.path.join(game, "data.json"), "rb").read()
            if new_data != orig_data:
                os.makedirs(os.path.join(pack, "data"))
                open(os.path.join(pack, "data", "data.json"), "wb").write(new_data)
                root["data"] = ["", "json"]
            loader = {"Version": str(int(time.time() * 1000)), "GameAbbreviation": "SMC", "Name": name,
                      "GameVersion": game_ver, "BaseURL": BASE_URL, "RootFolder": root}
            json.dump(loader, open(os.path.join(pack, "loader.json"), "w", encoding="utf-8"), indent=2)
            shutil.make_archive(pack, "zip", out, name)
            ok.append(name)
    print(f"\nMade {len(ok)} modpacks for {game_ver} in {out}/")
    for c, why in failed: print(f"  needs a fix: {c}: {why}")

if __name__ == "__main__":
    if len(sys.argv) not in (4, 5): raise SystemExit(__doc__)
    main(*sys.argv[1:])
