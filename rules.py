"""Game rules, one fixed time step at a time. No pygame in this file."""

import json
import math
import os
import random


def load_data(path=None):
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "data", "game.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def distance(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


class Enemy:
    __slots__ = ("kind", "x", "y", "hp", "speed", "damage", "radius", "xp", "boss",
                 "next_hurt", "next_blade")

    def __init__(self, kind, x, y, hp, speed, damage, radius, xp, boss):
        self.kind = kind
        self.x = x
        self.y = y
        self.hp = hp
        self.speed = speed
        self.damage = damage
        self.radius = radius
        self.xp = xp
        self.boss = boss
        self.next_hurt = 0.0
        self.next_blade = 0.0


class Spark:
    __slots__ = ("x", "y", "vx", "vy", "damage", "radius")

    def __init__(self, x, y, vx, vy, damage, radius):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.damage = damage
        self.radius = radius


class Gem:
    __slots__ = ("x", "y", "xp")

    def __init__(self, x, y, xp):
        self.x = x
        self.y = y
        self.xp = xp


def schedule_for(spawning, t):
    """The last schedule row that has started at time t, or None."""
    row = None
    for entry in spawning["schedule"]:
        if entry["time"] <= t:
            row = entry
        else:
            break
    return row


class Game:
    def __init__(self, data, rng=None):
        self.data = data
        self.rng = rng if rng is not None else random.Random()
        self.reset()

    def reset(self):
        hero = self.data["hero"]
        self.hero_x = 0.0
        self.hero_y = 0.0
        self.max_hp = float(hero["hp"])
        self.hp = float(hero["hp"])
        self.radius = float(hero["radius"])
        self.enemies = []
        self.sparks = []
        self.gems = []
        self.steps = 0
        self.kills = 0
        self.lost = False
        self.won = False
        self.boss_spawned = False
        self.next_spawn_time = 0.0
        self.next_fire_time = 0.0
        self.next_ring_time = 0.0
        self.level = 1
        self.xp = 0.0
        self.pending_level_ups = 0
        self.awaiting_choice = False
        self.cards = []
        self.weapons = {self.data["starting_weapon"]: 1}
        self.passives = {name: 0 for name in self.data["passives"]}
        # Things that happened this step: main.py turns them into sounds and effects.
        self.events = []

    def take_events(self):
        """Give main.py everything that happened since the last time it asked."""
        events = self.events
        self.events = []
        return events

    def add_event(self, kind, x=None, y=None, amount=None):
        self.events.append((kind, x, y, amount))

    # --- numbers that depend on levels ---

    def level_cap(self):
        return self.data["level"]["max_level"]

    def hero_speed(self):
        per = self.data["passives"]["swift_boots"]["speed_up_per_level"]
        return self.data["hero"]["speed"] * (1 + per * self.passives["swift_boots"])

    def magnet_radius(self):
        per = self.data["passives"]["magnet"]["magnet_per_level"]
        return self.data["hero"]["magnet"] + per * self.passives["magnet"]

    def xp_needed(self):
        level = self.data["level"]
        return level["first_xp"] + level["xp_per_level"] * (self.level - 1)

    def spark_damage(self):
        w = self.data["weapons"]["spark_wand"]
        return w["damage"] + (self.weapons["spark_wand"] - 1) * w["damage_per_level"]

    def spark_interval(self):
        w = self.data["weapons"]["spark_wand"]
        shorter = (self.weapons["spark_wand"] - 1) * w["interval_minus_per_level"]
        return max(w["min_interval"], w["interval"] - shorter)

    def spark_count(self):
        w = self.data["weapons"]["spark_wand"]
        return w["count"] + sum(1 for lv in w["extra_spark_levels"]
                                if self.weapons["spark_wand"] >= lv)

    def blade_damage(self):
        w = self.data["weapons"]["spin_blades"]
        return w["damage"] + (self.weapons["spin_blades"] - 1) * w["damage_per_level"]

    def blade_count(self):
        w = self.data["weapons"]["spin_blades"]
        return w["blades"] + sum(1 for lv in w["extra_blade_levels"]
                                 if self.weapons["spin_blades"] >= lv)

    def blade_points(self):
        """Where the blades are right now, in world coordinates."""
        w = self.data["weapons"]["spin_blades"]
        count = self.blade_count()
        turn = math.tau * (self.time / w["turn_time"])
        points = []
        for i in range(count):
            angle = turn + math.tau * i / count
            points.append((self.hero_x + math.cos(angle) * w["radius"],
                           self.hero_y + math.sin(angle) * w["radius"]))
        return points

    def ring_damage(self):
        w = self.data["weapons"]["holy_ring"]
        return w["damage"] + (self.weapons["holy_ring"] - 1) * w["damage_per_level"]

    def ring_radius(self):
        w = self.data["weapons"]["holy_ring"]
        return w["radius"] + (self.weapons["holy_ring"] - 1) * w["radius_per_level"]

    # --- one step ---

    @property
    def time(self):
        """The clock in seconds: an exact multiple of the step, so it cannot drift."""
        return self.steps * self.data["dt"]

    @property
    def over(self):
        """True when this run has ended, by dying or by surviving to the end."""
        return self.lost or self.won

    def step(self, target):
        """Move everything forward by one fixed time step. target is (x, y) or None."""
        if self.over or self.awaiting_choice:
            return
        dt = self.data["dt"]
        self.steps += 1
        self.walk_hero(target, dt)
        self.spawn_enemies()
        self.despawn_enemies()
        self.move_enemies(dt)
        self.fire_sparks()
        self.move_sparks(dt)
        self.hit_blades()
        self.pulse_ring()
        self.move_gems(dt)
        self.hurt_hero()
        if self.hp <= 0:
            self.hp = 0.0
            self.lost = True
            self.add_event("lose", self.hero_x, self.hero_y)
        elif self.time >= self.data["goal_time"]:
            self.won = True
            self.add_event("win", self.hero_x, self.hero_y)

    def walk_hero(self, target, dt):
        if target is None:
            return
        hero = self.data["hero"]
        dx = target[0] - self.hero_x
        dy = target[1] - self.hero_y
        dist = math.hypot(dx, dy)
        if dist <= hero["stop_distance"]:
            return
        step = min(dist, self.hero_speed() * dt)
        self.hero_x += dx / dist * step
        self.hero_y += dy / dist * step

    def spawn_enemies(self):
        spawning = self.data["spawning"]
        while self.time >= self.next_spawn_time:
            self.next_spawn_time += spawning["interval"]
            row = schedule_for(spawning, self.time)
            if row is None:
                continue
            boss = row.get("boss")
            if boss and not self.boss_spawned and boss in self.data["enemies"]:
                self.boss_spawned = True
                self.enemies.append(self.make_enemy(boss))
            kinds = [k for k in row["types"] if k in self.data["enemies"]]
            if not kinds:
                continue
            need = row["min_alive"] - len(self.enemies)
            batch = min(need, spawning["max_per_interval"])
            for _ in range(max(0, batch)):
                if len(self.enemies) >= spawning["max_alive"]:
                    break
                self.enemies.append(self.make_enemy(self.rng.choice(kinds)))

    def make_enemy(self, kind, distance_from_hero=None):
        spawning = self.data["spawning"]
        stats = self.data["enemies"][kind]
        dist = spawning["spawn_radius"] if distance_from_hero is None else distance_from_hero
        angle = self.rng.uniform(0.0, math.tau)
        return Enemy(
            kind,
            self.hero_x + math.cos(angle) * dist,
            self.hero_y + math.sin(angle) * dist,
            float(stats["hp"]),
            float(stats["speed"]),
            float(stats["damage"]),
            float(stats["radius"]),
            float(stats["xp"]),
            bool(stats["boss"]),
        )

    def despawn_enemies(self):
        spawning = self.data["spawning"]
        keep = []
        for e in self.enemies:
            far = distance(e.x, e.y, self.hero_x, self.hero_y)
            if e.boss:
                if far > spawning["boss_return_radius"]:
                    self.bring_back(e)
                keep.append(e)
            elif far <= spawning["despawn_radius"]:
                keep.append(e)
        self.enemies = keep

    def bring_back(self, enemy):
        """The boss is never removed: it goes back to the circle the others come from."""
        spawning = self.data["spawning"]
        angle = self.rng.uniform(0.0, math.tau)
        enemy.x = self.hero_x + math.cos(angle) * spawning["spawn_radius"]
        enemy.y = self.hero_y + math.sin(angle) * spawning["spawn_radius"]

    def move_enemies(self, dt):
        for e in self.enemies:
            dx = self.hero_x - e.x
            dy = self.hero_y - e.y
            dist = math.hypot(dx, dy)
            if dist == 0:
                continue
            step = min(dist, e.speed * dt)
            e.x += dx / dist * step
            e.y += dy / dist * step

    def fire_sparks(self):
        if "spark_wand" not in self.weapons or self.time < self.next_fire_time:
            return
        w = self.data["weapons"]["spark_wand"]
        self.next_fire_time = self.time + self.spark_interval()
        if not self.enemies:
            return
        nearest = min(self.enemies, key=lambda e: distance(e.x, e.y,
                                                           self.hero_x, self.hero_y))
        if distance(nearest.x, nearest.y, self.hero_x, self.hero_y) > w["range"]:
            return
        base = math.atan2(nearest.y - self.hero_y, nearest.x - self.hero_x)
        count = self.spark_count()
        for i in range(count):
            angle = base + (i - (count - 1) / 2) * 0.15
            self.sparks.append(Spark(self.hero_x, self.hero_y,
                                     math.cos(angle) * w["speed"],
                                     math.sin(angle) * w["speed"],
                                     self.spark_damage(), float(w["radius"])))

    def move_sparks(self, dt):
        w = self.data["weapons"]["spark_wand"]
        keep = []
        for s in self.sparks:
            s.x += s.vx * dt
            s.y += s.vy * dt
            hit = None
            for e in self.enemies:
                if distance(s.x, s.y, e.x, e.y) <= s.radius + e.radius:
                    hit = e
                    break
            if hit is None:
                if distance(s.x, s.y, self.hero_x, self.hero_y) <= w["range"] + 40:
                    keep.append(s)
                continue
            self.damage_enemy(hit, s.damage)
        self.sparks = keep

    def hit_blades(self):
        if "spin_blades" not in self.weapons:
            return
        w = self.data["weapons"]["spin_blades"]
        for bx, by in self.blade_points():
            for e in self.enemies:
                if distance(bx, by, e.x, e.y) > w["blade_radius"] + e.radius:
                    continue
                if self.time < e.next_blade:
                    continue
                e.next_blade = self.time + w["hit_interval"]
                self.damage_enemy(e, self.blade_damage())
                break

    def pulse_ring(self):
        if "holy_ring" not in self.weapons or self.time < self.next_ring_time:
            return
        self.next_ring_time = self.time + self.data["weapons"]["holy_ring"]["interval"]
        radius = self.ring_radius()
        for e in list(self.enemies):
            if distance(e.x, e.y, self.hero_x, self.hero_y) <= radius:
                self.damage_enemy(e, self.ring_damage())

    def damage_enemy(self, enemy, amount):
        enemy.hp -= amount
        self.add_event("hit", enemy.x, enemy.y, amount)
        if enemy.hp <= 0 and enemy in self.enemies:
            self.enemies.remove(enemy)
            self.kills += 1
            self.add_event("death", enemy.x, enemy.y)
            if enemy.xp > 0:
                self.gems.append(Gem(enemy.x, enemy.y, enemy.xp))

    def move_gems(self, dt):
        gems = self.data["gems"]
        magnet = self.magnet_radius()
        keep = []
        for g in self.gems:
            dist = distance(g.x, g.y, self.hero_x, self.hero_y)
            if dist <= self.radius:
                self.pick_up(g)
                continue
            if dist <= magnet:
                step = min(dist, gems["speed"] * dt)
                g.x += (self.hero_x - g.x) / dist * step
                g.y += (self.hero_y - g.y) / dist * step
                if distance(g.x, g.y, self.hero_x, self.hero_y) <= self.radius:
                    self.pick_up(g)
                    continue
            keep.append(g)
        self.gems = keep

    def pick_up(self, gem):
        self.add_event("gem", gem.x, gem.y, gem.xp)
        self.gain_xp(gem.xp)

    def hurt_hero(self):
        interval = self.data["contact"]["hurt_interval"]
        for e in self.enemies:
            if distance(e.x, e.y, self.hero_x, self.hero_y) > e.radius + self.radius:
                continue
            if self.time < e.next_hurt:
                continue
            self.hp -= e.damage
            self.add_event("hurt", self.hero_x, self.hero_y, e.damage)
            e.next_hurt = self.time + interval
            if self.hp <= 0:
                return

    # --- XP, level-up and cards ---

    def gain_xp(self, amount):
        self.xp += amount
        while self.xp >= self.xp_needed():
            self.xp -= self.xp_needed()
            self.level += 1
            self.pending_level_ups += 1
            self.add_event("level_up", self.hero_x, self.hero_y)
        if self.pending_level_ups:
            self.open_cards()

    def card_pool(self):
        """Everything the hero may be offered right now."""
        pool = []
        for name, stats in self.data["weapons"].items():
            level = self.weapons.get(name, 0)
            if level >= self.level_cap():
                continue
            if level == 0 and len(self.weapons) >= self.data["max_weapons"]:
                continue
            if level == 0:
                pool.append({"kind": "weapon", "key": name, "level": 1,
                             "name": stats["name"], "text": stats["new_text"]})
            else:
                pool.append({"kind": "weapon", "key": name, "level": level + 1,
                             "name": stats["name"], "text": stats["up_text"]})
        for name, stats in self.data["passives"].items():
            level = self.passives[name]
            if level >= self.level_cap():
                continue
            text = stats["new_text"] if level == 0 else stats["up_text"]
            pool.append({"kind": "passive", "key": name, "level": level + 1,
                         "name": stats["name"], "text": text})
        return pool

    def open_cards(self):
        pool = self.card_pool()
        if not pool:
            heal = self.data["level"]["heal_when_nothing_left"]
            pool = [{"kind": "heal", "key": "heal", "level": 0,
                     "name": "Heal", "text": f"heal {heal} HP"}]
        count = min(self.data["level"]["cards"], len(pool))
        self.cards = self.rng.sample(pool, count)
        self.awaiting_choice = True

    def choose(self, index):
        """Take card number index, then show the next cards if more levels are waiting."""
        card = self.cards[index]
        kind = card["kind"]
        if kind == "heal":
            self.hp = min(self.max_hp, self.hp + self.data["level"]["heal_when_nothing_left"])
        elif kind == "weapon":
            self.weapons[card["key"]] = card["level"]
            if card["key"] == "holy_ring":
                self.next_ring_time = self.time
        else:
            self.passives[card["key"]] = card["level"]
            stats = self.data["passives"][card["key"]]
            if "hp_per_level" in stats:
                self.max_hp += stats["hp_per_level"]
                self.hp = min(self.max_hp, self.hp + stats["heal"])
        self.pending_level_ups -= 1
        if self.pending_level_ups:
            self.open_cards()
        else:
            self.cards = []
            self.awaiting_choice = False
