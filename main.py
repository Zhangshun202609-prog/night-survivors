"""Window, drawing, sound and input. The rules live in rules.py."""

import asyncio
import math
import os
import random

import pygame

import rules

FPS = 60


def load_pictures(data):
    """Only finished files from assets/ - make_assets.py made them, we never draw with Pillow."""
    assets = data["assets"]
    names = list(assets["copy"]) + [gem["out"] for gem in assets["gems"]]
    pictures = {}
    for name in names:
        path = os.path.join(assets["out_dir"], name)
        try:
            pictures[name] = pygame.image.load(path).convert_alpha()
        except pygame.error:
            raise SystemExit(f"Missing picture: {path}\nRun this first: python make_assets.py")
    return pictures


def load_sounds(data):
    """Load the finished files from sounds/, .ogg first then .wav. No sound device is fine."""
    try:
        pygame.mixer.init()
    except pygame.error:
        print("No audio device: the game runs silently.")
        return {}
    wanted = data["sounds"]["names"]
    sounds = {}
    for name in wanted:
        for suffix in (".ogg", ".wav"):
            path = os.path.join(data["sounds"]["dir"], name + suffix)
            if not os.path.exists(path):
                continue
            try:
                sound = pygame.mixer.Sound(path)
            except pygame.error:
                break
            sound.set_volume(data["sounds"]["volume"])
            sounds[name] = sound
            break
    missing = [name for name in wanted if name not in sounds]
    if missing:
        print(f"No sound files for: {', '.join(missing)}. Run: python make_sounds.py")
    return sounds


class App:
    def __init__(self, data, screen_size):
        self.data = data
        self.size = screen_size
        self.game = rules.Game(data)
        self.pictures = load_pictures(data)
        self.sounds = load_sounds(data)
        self.scaled = {}
        self.font = pygame.font.Font(None, 22)
        self.big_font = pygame.font.Font(None, 52)
        self.number_font = pygame.font.Font(None, data["feel"]["damage_number"]["size"])
        self.paused = False
        self.mouse_pos = (screen_size[0] / 2, screen_size[1] / 2)
        self.mouse_moved = False
        self.touch_pos = None
        self.clicked = False
        self.click_pos = None
        self.rng = random.Random()
        self.floaters = []
        self.flashes = []
        self.shake = 0.0
        self.last_play = {}

    def camera(self):
        return (self.game.hero_x - self.size[0] / 2,
                self.game.hero_y - self.size[1] / 2)

    def aim_in_world(self):
        """Where the hero walks to, in world coordinates (or None)."""
        x, y = self.touch_pos if self.touch_pos is not None else self.mouse_pos
        cam_x, cam_y = self.camera()
        return (x + cam_x, y + cam_y)

    def clear_feel(self):
        """Forget the damage numbers, flashes and shake when a new run starts."""
        self.floaters = []
        self.flashes = []
        self.shake = 0.0


def play(app, name):
    """Play a sound, but never more than once every min_gap seconds."""
    sound = app.sounds.get(name)
    if sound is None:
        return
    now = pygame.time.get_ticks() / 1000.0
    gap = app.data["sounds"]["min_gap"]
    if now - app.last_play.get(name, -gap) < gap:
        return
    app.last_play[name] = now
    sound.play()


def apply_events(app, seconds):
    """Turn what the rules reported into sounds and things you can see."""
    feel = app.data["feel"]
    for kind, x, y, amount in app.game.take_events():
        if kind == "hit":
            play(app, "hit")
            app.floaters.append({"x": x, "y": y, "age": 0.0, "text": str(int(round(amount)))})
        elif kind == "death":
            app.flashes.append({"x": x, "y": y, "age": 0.0})
        elif kind == "gem":
            play(app, "gem")
        elif kind == "level_up":
            play(app, "level_up")
        elif kind == "hurt":
            play(app, "hurt")
            app.shake = feel["hurt_shake"]["time"]
        elif kind in ("win", "lose"):
            play(app, "end")
    for item in app.floaters:
        item["age"] += seconds
    app.floaters = [f for f in app.floaters
                    if f["age"] < feel["damage_number"]["lifetime"]]
    for item in app.flashes:
        item["age"] += seconds
    app.flashes = [f for f in app.flashes if f["age"] < feel["death_flash"]["lifetime"]]
    app.shake = max(0.0, app.shake - seconds)


def shake_offset(app):
    """How far the picture jumps this frame. Only drawing moves, aiming does not."""
    if app.shake <= 0:
        return (0.0, 0.0)
    feel = app.data["feel"]["hurt_shake"]
    strength = feel["amount"] * (app.shake / feel["time"])
    return (app.rng.uniform(-strength, strength), app.rng.uniform(-strength, strength))


def read_events(app):
    """Pump the pygame queue. Returns True when the window should close."""
    app.clicked = False
    app.mouse_moved = False
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_p:
            app.paused = not app.paused
        elif event.type == pygame.MOUSEMOTION:
            app.mouse_pos = event.pos
            app.mouse_moved = True
        elif event.type == pygame.MOUSEBUTTONDOWN:
            app.mouse_pos = event.pos
            app.mouse_moved = True
            app.clicked = True
            app.click_pos = event.pos
        elif event.type in (pygame.FINGERDOWN, pygame.FINGERMOTION):
            app.touch_pos = (event.x * app.size[0], event.y * app.size[1])
            if event.type == pygame.FINGERDOWN:
                app.clicked = True
                app.click_pos = app.touch_pos
        elif event.type == pygame.FINGERUP:
            app.touch_pos = None
    return False


def draw_floor(screen, app, cam_x, cam_y):
    floor = app.data["floor"]
    tile = floor["tile"]
    image = app.pictures[floor["picture"]]
    x = math.floor(cam_x / tile) * tile
    while x < cam_x + app.size[0]:
        y = math.floor(cam_y / tile) * tile
        while y < cam_y + app.size[1]:
            screen.blit(image, (x - cam_x, y - cam_y))
            y += tile
        x += tile


def picture(app, name, scale):
    key = (name, scale)
    if key not in app.scaled:
        image = app.pictures[name]
        if scale != 1:
            size = (round(image.get_width() * scale), round(image.get_height() * scale))
            image = pygame.transform.scale(image, size)
        app.scaled[key] = image
    return app.scaled[key]


def blit_centred(screen, image, x, y):
    screen.blit(image, (round(x - image.get_width() / 2), round(y - image.get_height() / 2)))


def owned_line(app, game):
    """What you have, for example 'Spark 2  Blades 1  Boots 1'."""
    parts = []
    for name, level in game.weapons.items():
        parts.append(f"{app.data['weapons'][name]['label']} {level}")
    for name, level in game.passives.items():
        if level:
            parts.append(f"{app.data['passives'][name]['label']} {level}")
    return "  ".join(parts)


def draw_hud(screen, app):
    data = app.data
    game = app.game
    light = (240, 240, 240)
    bar(screen, 10, 10, 150, 14, game.hp / game.max_hp, (220, 60, 60))
    bar(screen, 10, 28, 150, 10, game.xp / game.xp_needed(), (70, 130, 240))
    screen.blit(app.font.render(f"Lv {game.level}", True, light), (168, 26))
    clock = app.font.render(f"{fmt_time(game.time)} / {fmt_time(data['goal_time'])}",
                            True, light)
    screen.blit(clock, (app.size[0] - clock.get_width() - 10, 10))
    screen.blit(app.font.render(f"Kills {game.kills}", True, light), (10, 44))
    bottom = app.font.render(owned_line(app, game), True, light)
    screen.blit(bottom, (10, app.size[1] - bottom.get_height() - 10))
    if app.paused and not game.over and not game.awaiting_choice:
        centre_text(screen, app, "PAUSED", 0)
    if game.over:
        screen.fill((18, 18, 26))
        centre_text(screen, app, "VICTORY" if game.won else "GAME OVER", -60)
        for i, line in enumerate((f"time {fmt_time(game.time)}", f"kills {game.kills}",
                                  f"Lv {game.level}", "click to play again")):
            centre_text(screen, app, line, 0 + i * 26, small=True)


def card_rects(app):
    """Where the level-up cards go on the screen."""
    cards = app.data["cards"]
    count = len(app.game.cards)
    total = count * cards["height"] + max(0, count - 1) * cards["gap"]
    top = (app.size[1] - total) // 2
    left = (app.size[0] - cards["width"]) // 2
    return [pygame.Rect(left, top + i * (cards["height"] + cards["gap"]),
                        cards["width"], cards["height"]) for i in range(count)]


def card_at(app, pos):
    """Which card the pointer is on, or None."""
    if pos is None:
        return None
    for index, rect in enumerate(card_rects(app)):
        if rect.collidepoint(pos):
            return index
    return None


def draw_cards(screen, app):
    screen.fill((12, 12, 18))
    title = app.font.render("Pick one", True, (245, 245, 245))
    screen.blit(title, title.get_rect(midtop=(app.size[0] // 2, 20)))
    for rect, card in zip(card_rects(app), app.game.cards):
        pygame.draw.rect(screen, (44, 48, 66), rect)
        pygame.draw.rect(screen, (200, 200, 200), rect, 2)
        name = rect.inflate(-30, 0)
        level = f"  Lv {card['level']}" if card["level"] else ""
        screen.blit(app.font.render(card["name"] + level, True, (250, 230, 140)),
                    name.move(0, 14))
        screen.blit(app.font.render(card["text"], True, (235, 235, 235)), name.move(0, 46))


def centre_text(screen, app, line, dy, small=False):
    font = app.font if small else app.big_font
    image = font.render(line, True, (245, 245, 245))
    screen.blit(image, image.get_rect(center=(app.size[0] // 2, app.size[1] // 2 + dy)))


def bar(screen, x, y, w, h, fraction, colour):
    screen.fill((30, 32, 40), pygame.Rect(x, y, w, h))
    screen.fill(colour, pygame.Rect(x, y, int(max(0.0, min(1.0, fraction)) * w), h))
    pygame.draw.rect(screen, (200, 200, 200), pygame.Rect(x, y, w, h), 1)


def fmt_time(seconds):
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def flash_image(app, radius):
    """One soft white round flash, made once and reused."""
    key = ("flash", radius)
    if key not in app.scaled:
        image = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(image, (255, 255, 255, 255), (radius, radius), radius)
        app.scaled[key] = image
    return app.scaled[key]


def draw_feel(screen, app, cam_x, cam_y):
    feel = app.data["feel"]
    flash = feel["death_flash"]
    for item in app.flashes:
        left = 1.0 - item["age"] / flash["lifetime"]
        image = flash_image(app, flash["radius"]).copy()
        image.set_alpha(round(255 * left))
        blit_centred(screen, image, item["x"] - cam_x, item["y"] - cam_y)
    number = feel["damage_number"]
    colour = tuple(number["color"])
    for item in app.floaters:
        fraction = item["age"] / number["lifetime"]
        image = app.number_font.render(item["text"], True, colour)
        y = item["y"] - cam_y - fraction * number["rise"]
        blit_centred(screen, image, item["x"] - cam_x, y)


def draw(screen, app):
    cam_x, cam_y = app.camera()
    shake_x, shake_y = shake_offset(app)
    cam_x += shake_x
    cam_y += shake_y
    data = app.data
    game = app.game
    draw_floor(screen, app, cam_x, cam_y)
    hero_pos = (game.hero_x - cam_x, game.hero_y - cam_y)
    if "holy_ring" in game.weapons:
        ring = data["weapons"]["holy_ring"]
        pygame.draw.circle(screen, ring["color"], hero_pos, game.ring_radius(), 2)
    for gem in game.gems:
        name = data["gems"]["by_xp"][str(int(gem.xp))]
        blit_centred(screen, picture(app, name, 1), gem.x - cam_x, gem.y - cam_y)
    for enemy in game.enemies:
        stats = data["enemies"][enemy.kind]
        blit_centred(screen, picture(app, stats["picture"], stats["scale"]),
                     enemy.x - cam_x, enemy.y - cam_y)
    spark = data["weapons"]["spark_wand"]
    for s in game.sparks:
        pygame.draw.circle(screen, spark["color"], (s.x - cam_x, s.y - cam_y), s.radius)
    blit_centred(screen, picture(app, data["hero"]["picture"], 1), *hero_pos)
    if "spin_blades" in game.weapons:
        blades = data["weapons"]["spin_blades"]
        image = picture(app, blades["picture"], blades["picture_scale"])
        for bx, by in game.blade_points():
            blit_centred(screen, image, bx - cam_x, by - cam_y)
    draw_feel(screen, app, cam_x, cam_y)
    draw_hud(screen, app)
    if game.awaiting_choice:
        draw_cards(screen, app)


async def main():
    data = rules.load_data()
    size = (data["screen"]["width"], data["screen"]["height"])
    pygame.init()
    screen = pygame.display.set_mode(size)
    pygame.display.set_caption("Night Survivors")
    clock = pygame.time.Clock()
    app = App(data, size)
    dt = data["dt"]
    leftover = 0.0
    running = True
    while running:
        running = not read_events(app)
        if not app.mouse_moved:
            app.mouse_pos = pygame.mouse.get_pos()

        seconds = clock.tick(FPS) / 1000.0
        leftover = min(leftover + seconds, 0.2)
        if app.clicked:
            if app.game.awaiting_choice:
                index = card_at(app, app.click_pos)
                if index is not None:
                    app.game.choose(index)
            elif app.game.over:
                app.game.reset()
                app.clear_feel()
                leftover = 0.0
        while leftover >= dt:
            leftover -= dt
            if not app.paused:
                app.game.step(app.aim_in_world())

        apply_events(app, seconds)
        draw(screen, app)
        pygame.display.flip()
        await asyncio.sleep(0)

    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
