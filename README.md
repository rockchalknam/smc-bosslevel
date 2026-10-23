# Herons Mario Hub

The VRMS Herons Super Mario Construct Arcade: student levels by period plus choose-your-own boss, all on one site. Students and families can play without any setup.

## Links

- **Hub (start here):** https://rockchalknam.github.io/smc-bosslevel/hub.html
- **Boss Picker:** https://rockchalknam.github.io/smc-bosslevel/bosses.html
- **Boss Maker:** https://rockchalknam.github.io/smc-bosslevel/boss-maker.html

## How students turn things in

Everything goes through one form: **Herons Super Mario Construct Arcade**. A dropdown asks if it's a **level code** or a **boss zip**.

- **Level code:** shows up on the Hub within a few minutes. No rebuild needed.
- **Boss zip:** lands in `turned-in/` and the site rebuilds in about 3 to 5 minutes.

No teacher approval step. Old SMC-WCB levels stay off the Hub.

## How students play

1. Pick a boss up top (or keep Bowser).
2. Pick a level. The code copies automatically.
3. Open the game, click **Play Level**, and press **Ctrl+V**.

## Teacher jobs

- **Add a boss by hand:** open `turned-in`, click **Add file > Upload files**, drag in the zip (named with the student's code name), and commit.
- **Remove a boss:** open its zip in `turned-in`, click the trash icon, and commit.
- **Guest bosses** (like Mr. Nam) show first, right after Normal Bowser. Add a code name to `FEATURED` in `build_site.py`.
- **Watch a build:** the **Actions** tab. Green check = live.

Every Monday it also checks Level Share Square for a game update and rebuilds by itself.
