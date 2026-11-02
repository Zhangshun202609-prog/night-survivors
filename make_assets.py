"""Makes the picture files in assets/ from the originals in raw_art/.

Run it yourself when the numbers in data/game.json change:  python make_assets.py
raw_art/ is only ever read, never changed.
"""

import os

from PIL import Image

import rules


def nearest_upscale(image, scale):
    """Bigger pixels, no blurring: every source pixel becomes a scale x scale block."""
    return image.resize((image.width * scale, image.height * scale), Image.NEAREST)


def tint(image, dark, bright):
    """Keep the shape and the shading, but colour the gem between two colours."""
    source = image.load()
    result = Image.new("RGBA", image.size)
    target = result.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = source[x, y]
            if a == 0:
                target[x, y] = (0, 0, 0, 0)
                continue
            light = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            colour = tuple(round(d + (hi - d) * light) for d, hi in zip(dark, bright))
            target[x, y] = colour + (a,)
    return result


def main():
    data = rules.load_data()
    assets = data["assets"]
    scale = assets["scale"]
    os.makedirs(assets["out_dir"], exist_ok=True)

    for name in assets["copy"]:
        path = os.path.join(assets["raw_dir"], name)
        image = Image.open(path).convert("RGBA")
        big = nearest_upscale(image, scale)
        big.save(os.path.join(assets["out_dir"], name))
        print(f"{name}: {image.width}x{image.height} -> {big.width}x{big.height}")

    for gem in assets["gems"]:
        path = os.path.join(assets["raw_dir"], gem["source"])
        image = Image.open(path).convert("RGBA")
        big = nearest_upscale(tint(image, gem["dark"], gem["bright"]), scale)
        out = os.path.join(assets["out_dir"], gem["out"])
        big.save(out)
        print(f"{gem['out']}: XP {gem['xp']} gem, {big.width}x{big.height}")

    print(f"done: {len(assets['copy']) + len(assets['gems'])} files in {assets['out_dir']}/")


if __name__ == "__main__":
    main()
