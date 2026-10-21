# Kirby Inhale boot animation

The Windows host shows Kirby's Neutral B Inhale in the lower-right corner until
the game's first present. `runtime/loading_anim.c` uses a transparent PNG atlas;
it never paints over a game frame. `SSBU_LOADING_ANIM=0` disables it.

The original animated hitbox comes from [Kirby on Ultimate Frame Data](https://ultimateframedata.com/kirby),
specifically [the Inhale loop](https://ultimateframedata.com/hitboxes/kirby/KirbyInhale.gif).
Ultimate Frame Data is by MetalMusicMan; its Smash Ultimate hitbox credits include
Zeckemyro. `loading_kirby.json` records the original URL and source SHA-256.

The preparation separates Kirby from the viewer's opaque debug volumes and
replaces those volumes with the website's `HitSphere` style: cyan/pale rims,
low-opacity fills, curved meridians and a restrained halo. Kirby retains the
source animation with a fixed crop and baseline; the mouth opening is repainted
where the original search-volume overlay obscures it. The spheres are stylized
loading art, not a frame-data visualization.

A two-pixel bob, gentle breathing, sphere pulsation and cyan suction motes keep
the image moving. The 60-frame cycle lasts two seconds at 30 FPS; it uses no
runtime decoder or network access.

Regenerate the atlas and a preview from the repository root:

```powershell
python tools/ui/loading_inhale.py --preview ../ui_work/kirby-inhale-loading-v2.gif
```

If the source is missing, add `--download` to fetch the exact asset above.
`scripts/setup.py` and `scripts/run.py` copy `loading_kirby.png` beside the host.
The frame constants in `runtime/loading_anim.c` must match `loading_kirby.json`.

Verified locally on 2026-10-21: Windows UI host booted, displayed Kirby, stopped
GDI painting at the game's first present, and reached the Arena menu with copied
saves. Normal, UI and legacy rollback hosts all compiled and linked successfully.
