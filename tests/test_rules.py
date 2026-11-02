import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rules


def new_game(seed=7, **changes):
    data = rules.load_data()
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value
    return rules.Game(data, random.Random(seed))


def no_spawns(game):
    game.data["spawning"]["schedule"] = []


def still_and_tough(game):
    game.data["enemies"]["bat"]["hp"] = 100000
    game.data["enemies"]["bat"]["speed"] = 0


def tough_hero(game):
    """A hero that cannot die, so a long wave test is about the waves only."""
    game.max_hp = game.hp = 10 ** 9


def run(game, seconds, target=None):
    steps = int(round(seconds / game.data["dt"]))
    for _ in range(steps):
        game.step(target)


def take_card(game, key):
    """Pick the card for this weapon or passive, as the level-up screen would."""
    card = next(c for c in game.card_pool() if c["key"] == key)
    game.cards = [card]
    game.pending_level_ups = 1
    game.choose(0)
    return card


class SpawningTests(unittest.TestCase):
    def test_one_second_spawns_at_most_the_limit(self):
        game = new_game()
        game.data["spawning"]["schedule"] = [{"time": 0.0, "types": ["bat"],
                                              "min_alive": 100}]
        game.data["spawning"]["max_alive"] = 100
        run(game, game.data["dt"])
        self.assertEqual(len(game.enemies), game.data["spawning"]["max_per_interval"])

    def test_bats_appear_until_the_minimum(self):
        game = new_game()
        still_and_tough(game)
        game.weapons = {}
        minimum = game.data["spawning"]["schedule"][0]["min_alive"]
        run(game, minimum / game.data["spawning"]["max_per_interval"] + 1.0)
        self.assertEqual(len(game.enemies), minimum)
        self.assertTrue(all(enemy.kind == "bat" for enemy in game.enemies))

    def test_enemies_start_on_the_spawn_circle(self):
        game = new_game()
        still_and_tough(game)
        game.weapons = {}
        run(game, 1.0)
        radius = game.data["spawning"]["spawn_radius"]
        for enemy in game.enemies:
            far = rules.distance(enemy.x, enemy.y, game.hero_x, game.hero_y)
            self.assertAlmostEqual(far, radius, places=3)

    def test_enemies_walk_toward_the_hero(self):
        game = new_game()
        no_spawns(game)
        game.weapons = {}
        still_and_tough(game)
        game.enemies = [game.make_enemy("bat", 380)]
        run(game, 1.0)
        near = rules.distance(game.enemies[0].x, game.enemies[0].y,
                              game.hero_x, game.hero_y)
        self.assertAlmostEqual(near, 380 - game.data["enemies"]["bat"]["speed"], places=3)

    def test_far_enemies_are_removed(self):
        game = new_game()
        still_and_tough(game)
        game.weapons = {}
        run(game, 0.5)
        count = len(game.enemies)
        game.enemies[0].x = game.hero_x + game.data["spawning"]["despawn_radius"] + 1
        run(game, game.data["dt"])
        self.assertEqual(len(game.enemies), count - 1)

    def test_never_more_than_the_cap(self):
        game = new_game(spawning={"max_alive": 15, "schedule": [
            {"time": 0.0, "types": ["bat"], "min_alive": 100}]})
        still_and_tough(game)
        game.weapons = {}
        run(game, 5.0)
        self.assertEqual(len(game.enemies), 15)

    def test_rows_only_spawn_enemies_that_exist_in_the_data(self):
        game = new_game()
        game.data["enemies"] = {}
        run(game, 3.0)
        self.assertEqual(game.enemies, [])


class WalkingTests(unittest.TestCase):
    def test_hero_walks_toward_the_pointer(self):
        game = new_game()
        no_spawns(game)
        run(game, 1.0, target=(500, 0))
        self.assertGreater(game.hero_x, 0)
        self.assertEqual(game.hero_y, 0)

    def test_hero_stops_inside_the_dead_zone(self):
        game = new_game()
        run(game, 1.0, target=(game.data["hero"]["stop_distance"] - 1, 0))
        self.assertEqual(game.hero_x, 0)

    def test_hero_speed(self):
        game = new_game()
        no_spawns(game)
        run(game, 1.0, target=(1000, 0))
        self.assertAlmostEqual(game.hero_x, game.data["hero"]["speed"], places=6)


class SparkWandTests(unittest.TestCase):
    def test_level_one_numbers(self):
        game = new_game()
        wand = game.data["weapons"]["spark_wand"]
        self.assertEqual(game.spark_count(), wand["count"])
        self.assertEqual(game.spark_damage(), wand["damage"])
        self.assertEqual(game.spark_interval(), wand["interval"])

    def test_extra_sparks_at_levels_three_and_five(self):
        game = new_game()
        counts = {}
        for level in (1, 2, 3, 4, 5):
            game.weapons["spark_wand"] = level
            counts[level] = game.spark_count()
        self.assertEqual(counts, {1: 1, 2: 1, 3: 2, 4: 2, 5: 3})

    def test_damage_and_interval_change_with_level(self):
        game = new_game()
        game.weapons["spark_wand"] = 3
        wand = game.data["weapons"]["spark_wand"]
        self.assertEqual(game.spark_damage(), wand["damage"] + 2 * wand["damage_per_level"])
        self.assertAlmostEqual(game.spark_interval(),
                               wand["interval"] - 2 * wand["interval_minus_per_level"])

    def test_sparks_kill_the_nearest_enemy(self):
        game = new_game()
        no_spawns(game)
        game.enemies = [game.make_enemy("bat", 100)]
        run(game, 1.0)
        self.assertEqual(game.kills, 1)
        self.assertEqual(game.enemies, [])

    def test_no_shooting_when_no_enemy_is_alive(self):
        game = new_game()
        no_spawns(game)
        run(game, 2.0)
        self.assertEqual(game.sparks, [])

    def test_a_spark_only_hits_once(self):
        game = new_game()
        no_spawns(game)
        still_and_tough(game)
        game.enemies = [game.make_enemy("bat", 60)]
        run(game, 2.0)
        shots = 3  # every 0.8 s inside 2 s
        self.assertEqual(game.enemies[0].hp,
                         100000 - shots * game.data["weapons"]["spark_wand"]["damage"])
        self.assertEqual(game.sparks, [])


class SpinBladesTests(unittest.TestCase):
    def blades_game(self):
        game = new_game()
        no_spawns(game)
        still_and_tough(game)
        game.weapons = {"spin_blades": 1}
        blades = game.data["weapons"]["spin_blades"]
        enemy = game.make_enemy("bat", 0)
        enemy.x = game.hero_x + blades["radius"]
        enemy.y = game.hero_y
        game.enemies = [enemy]
        return game, enemy

    def test_blades_cut_an_enemy_in_their_path(self):
        game, enemy = self.blades_game()
        run(game, 1.0)
        hits = 2  # the blades pass this point every 0.75 s
        self.assertEqual(enemy.hp, 100000 - hits * game.blade_damage())

    def test_blade_count_and_damage_per_level(self):
        game = new_game()
        counts = {}
        for level in (1, 2, 3, 4, 5):
            game.weapons["spin_blades"] = level
            counts[level] = game.blade_count()
        self.assertEqual(counts, {1: 2, 2: 3, 3: 3, 4: 4, 5: 4})
        game.weapons["spin_blades"] = 4
        self.assertEqual(game.blade_damage(),
                         game.data["weapons"]["spin_blades"]["damage"] + 3 * 3)

    def test_blades_stay_the_right_distance_from_the_hero(self):
        game = new_game()
        game.weapons["spin_blades"] = 1
        radius = game.data["weapons"]["spin_blades"]["radius"]
        for point in game.blade_points():
            far = rules.distance(point[0], point[1], game.hero_x, game.hero_y)
            self.assertAlmostEqual(far, radius, places=6)


class HolyRingTests(unittest.TestCase):
    def ring_game(self, enemy_distance):
        game = new_game()
        no_spawns(game)
        still_and_tough(game)
        game.weapons = {"holy_ring": 1}
        enemy = game.make_enemy("bat", 0)
        enemy.x = game.hero_x + enemy_distance
        enemy.y = game.hero_y
        game.enemies = [enemy]
        return game, enemy

    def test_the_ring_hurts_enemies_inside_it(self):
        game, enemy = self.ring_game(40)
        run(game, 1.0)
        pulses = 2  # every 0.5 s
        self.assertEqual(enemy.hp, 100000 - pulses * game.ring_damage())

    def test_the_ring_ignores_enemies_outside_it(self):
        game, enemy = self.ring_game(200)
        run(game, 1.0)
        self.assertEqual(enemy.hp, 100000)

    def test_ring_grows_with_levels(self):
        game = new_game()
        ring = game.data["weapons"]["holy_ring"]
        game.weapons["holy_ring"] = 3
        self.assertEqual(game.ring_radius(), ring["radius"] + 2 * ring["radius_per_level"])
        self.assertEqual(game.ring_damage(), ring["damage"] + 2 * ring["damage_per_level"])


class GemTests(unittest.TestCase):
    def test_a_dead_enemy_drops_a_gem_of_its_xp(self):
        game = new_game()
        no_spawns(game)
        game.enemies = [game.make_enemy("bat", 100)]
        run(game, 1.0)
        self.assertEqual(len(game.gems), 1)
        self.assertEqual(game.gems[0].xp, game.data["enemies"]["bat"]["xp"])

    def test_a_gem_outside_the_magnet_radius_still_sits_there(self):
        game = new_game()
        no_spawns(game)
        game.weapons = {}
        game.gems = [rules.Gem(game.hero_x + 400, game.hero_y, 1)]
        run(game, 1.0)
        self.assertAlmostEqual(game.gems[0].x, game.hero_x + 400, places=6)

    def test_a_gem_inside_the_magnet_radius_flys_in_and_gives_xp(self):
        game = new_game()
        no_spawns(game)
        game.weapons = {}
        game.gems = [rules.Gem(game.hero_x + 30, game.hero_y, 1)]
        run(game, 1.0)
        self.assertEqual(game.gems, [])
        self.assertEqual(game.xp, 1)

    def test_the_magnet_item_widens_the_pickup_range(self):
        game = new_game()
        no_spawns(game)
        game.weapons = {}
        take_card(game, "magnet")
        self.assertEqual(game.magnet_radius(),
                         game.data["hero"]["magnet"] + game.data["passives"]["magnet"]
                         ["magnet_per_level"])


class LevelUpTests(unittest.TestCase):
    def test_xp_needed_grows_by_three(self):
        game = new_game()
        needed = []
        for level in (1, 2, 3, 4):
            game.level = level
            needed.append(game.xp_needed())
        self.assertEqual(needed, [5, 8, 11, 14])

    def test_filling_the_bar_levels_up_and_shows_cards(self):
        game = new_game()
        no_spawns(game)
        game.gain_xp(5)
        self.assertEqual(game.level, 2)
        self.assertEqual(game.xp, 0)
        self.assertTrue(game.awaiting_choice)
        self.assertEqual(len(game.cards), game.data["level"]["cards"])

    def test_the_world_waits_while_you_pick_a_card(self):
        game = new_game()
        no_spawns(game)
        game.gain_xp(5)
        frozen = game.time
        run(game, 1.0)
        self.assertEqual(game.time, frozen)
        game.choose(0)
        self.assertFalse(game.awaiting_choice)
        run(game, 1.0)
        self.assertGreater(game.time, frozen)

    def test_two_levels_at_once_need_two_picks(self):
        game = new_game()
        no_spawns(game)
        game.gain_xp(13)
        self.assertEqual(game.level, 3)
        self.assertEqual(game.pending_level_ups, 2)
        game.choose(0)
        self.assertTrue(game.awaiting_choice)
        game.choose(0)
        self.assertFalse(game.awaiting_choice)

    def test_cards_are_never_already_at_max_level(self):
        game = new_game()
        cap = game.level_cap()
        for name in game.data["weapons"]:
            game.weapons[name] = cap
        for name in game.data["passives"]:
            game.passives[name] = cap
        game.weapons["spark_wand"] = cap - 1
        keys = [card["key"] for card in game.card_pool()]
        self.assertEqual(keys, ["spark_wand"])

    def test_a_fourth_weapon_is_never_offered(self):
        game = new_game()
        game.weapons = {"spark_wand": 1, "spin_blades": 1}
        game.data["max_weapons"] = 2
        pool = game.card_pool()
        self.assertTrue(all(card["key"] in game.weapons or card["kind"] == "passive"
                            for card in pool))
        upgrades = [card for card in pool if card["kind"] == "weapon"]
        self.assertEqual(sorted(card["key"] for card in upgrades),
                         ["spark_wand", "spin_blades"])
        self.assertTrue(all(card["level"] == 2 for card in upgrades))

    def test_nothing_left_means_a_heal_card(self):
        game = new_game()
        cap = game.level_cap()
        game.weapons = {name: cap for name in game.data["weapons"]}
        game.passives = {name: cap for name in game.data["passives"]}
        game.hp = 20
        game.open_cards()
        self.assertEqual([card["kind"] for card in game.cards], ["heal"])
        game.choose(0)
        self.assertEqual(game.hp, 20 + game.data["level"]["heal_when_nothing_left"])

    def test_swift_boots_make_the_hero_faster(self):
        game = new_game()
        no_spawns(game)
        take_card(game, "swift_boots")
        self.assertAlmostEqual(game.hero_speed(),
                               game.data["hero"]["speed"] * 1.1, places=6)

    def test_big_heart_adds_max_hp_and_heals(self):
        game = new_game()
        no_spawns(game)
        game.hp = 50
        take_card(game, "big_heart")
        heart = game.data["passives"]["big_heart"]
        self.assertEqual(game.max_hp, game.data["hero"]["hp"] + heart["hp_per_level"])
        self.assertEqual(game.hp, 50 + heart["heal"])


class WaveTests(unittest.TestCase):
    def world_without_weapons(self, **changes):
        game = new_game(**changes)
        game.weapons = {}
        tough_hero(game)
        return game

    def test_enemy_numbers_match_the_design(self):
        data = rules.load_data()
        self.assertEqual(data["enemies"]["slime"]["hp"], 30)
        self.assertEqual(data["enemies"]["ghost"]["speed"], 135)
        self.assertGreater(data["enemies"]["ghost"]["speed"], data["hero"]["speed"])
        self.assertEqual(data["enemies"]["demon"]["hp"], 800)
        self.assertEqual(data["enemies"]["demon"]["xp"], 0)
        self.assertEqual(data["enemies"]["demon"]["scale"], 2)

    def test_slimes_then_ghosts_join_the_wave(self):
        game = self.world_without_weapons()
        run(game, 31.0)
        kinds = {enemy.kind for enemy in game.enemies}
        self.assertIn("slime", kinds)
        self.assertNotIn("ghost", kinds)
        run(game, 16.0)
        self.assertIn("ghost", {enemy.kind for enemy in game.enemies})

    def test_the_number_alive_follows_the_table(self):
        game = self.world_without_weapons()
        run(game, 16.0)
        self.assertEqual(len(game.enemies), 20)
        run(game, 15.0)
        self.assertEqual(len(game.enemies), 28)

    def test_the_boss_appears_once_at_its_time(self):
        game = self.world_without_weapons()
        run(game, 89.0)
        self.assertEqual([e for e in game.enemies if e.boss], [])
        run(game, 3.0)
        bosses = [e for e in game.enemies if e.boss]
        self.assertEqual(len(bosses), 1)
        self.assertEqual(bosses[0].kind, "demon")
        run(game, 20.0)
        self.assertEqual(len([e for e in game.enemies if e.boss]), 1)

    def test_the_boss_is_sent_back_instead_of_removed(self):
        game = self.world_without_weapons()
        run(game, 92.0)
        boss = next(e for e in game.enemies if e.boss)
        boss.x = game.hero_x + game.data["spawning"]["boss_return_radius"] + 300
        boss.y = game.hero_y
        run(game, game.data["dt"])
        self.assertIn(boss, game.enemies)
        far = rules.distance(boss.x, boss.y, game.hero_x, game.hero_y)
        spawn = game.data["spawning"]["spawn_radius"]
        self.assertLess(far, spawn + boss.speed * game.data["dt"] + 1)
        self.assertGreater(far, spawn - boss.speed * game.data["dt"] - 1)

    def test_the_boss_drops_no_gem_because_it_is_worth_zero_xp(self):
        game = new_game()
        no_spawns(game)
        game.weapons = {}
        boss = game.make_enemy("demon", 50)
        game.enemies = [boss]
        game.damage_enemy(boss, 10000)
        self.assertEqual(game.kills, 1)
        self.assertEqual(game.gems, [])

    def test_victory_at_two_minutes(self):
        game = self.world_without_weapons(goal_time=2.0)
        run(game, 2.0)
        self.assertTrue(game.won)
        self.assertFalse(game.lost)
        self.assertTrue(game.over)
        frozen = game.time
        run(game, 1.0)
        self.assertEqual(game.time, frozen)

    def test_the_real_goal_is_two_minutes(self):
        self.assertEqual(rules.load_data()["goal_time"], 120.0)


class ContactDamageTests(unittest.TestCase):
    def touching_enemy(self, game):
        no_spawns(game)
        still_and_tough(game)
        game.weapons = {}
        game.enemies = [game.make_enemy("bat", 0)]
        return game.enemies[0]

    def test_one_touch_costs_one_hit(self):
        game = new_game()
        self.touching_enemy(game)
        run(game, 0.4)
        self.assertEqual(game.hp,
                         game.data["hero"]["hp"] - game.data["enemies"]["bat"]["damage"])

    def test_the_same_enemy_cannot_hurt_twice_in_a_row(self):
        game = new_game()
        self.touching_enemy(game)
        run(game, 1.0)
        self.assertEqual(game.hp,
                         game.data["hero"]["hp"] - 2 * game.data["enemies"]["bat"]["damage"])

    def test_losing_the_game(self):
        game = new_game()
        enemy = self.touching_enemy(game)
        game.hp = 1
        run(game, 0.1)
        self.assertTrue(game.lost)
        self.assertEqual(game.hp, 0)
        frozen = (game.time, enemy.x)
        run(game, 1.0)
        self.assertEqual(game.time, frozen[0])
        self.assertEqual(enemy.x, frozen[1])


class EventTests(unittest.TestCase):
    """The rules tell the window what happened, so it can play sounds and draw effects."""

    def kinds(self, game):
        return [event[0] for event in game.take_events()]

    def test_hitting_an_enemy_reports_a_hit_and_a_death(self):
        game = new_game()
        game.data["spawning"]["schedule"] = []
        game.enemies = [game.make_enemy("bat", 20)]
        run(game, 2.0)
        kinds = self.kinds(game)
        self.assertIn("hit", kinds)
        self.assertIn("death", kinds)
        self.assertEqual(game.kills, 1)

    def test_picking_up_a_gem_is_reported(self):
        game = new_game()
        no_spawns(game)
        game.weapons = {}
        game.gems = [rules.Gem(0.0, 0.0, game.data["level"]["first_xp"])]
        run(game, 0.1)
        self.assertIn("gem", self.kinds(game))

    def test_a_level_up_is_reported_once_per_level(self):
        game = new_game()
        no_spawns(game)
        game.gain_xp(game.data["level"]["first_xp"])
        self.assertEqual(self.kinds(game), ["level_up"])
        game.gain_xp(game.xp_needed())
        self.assertEqual(self.kinds(game), ["level_up"])
        game.gain_xp(game.xp_needed())
        self.assertEqual(self.kinds(game), ["level_up"])

    def test_two_levels_at_once_report_two_events(self):
        game = new_game()
        no_spawns(game)
        game.gain_xp(30)
        kinds = self.kinds(game)
        self.assertGreaterEqual(len(kinds), 2)
        self.assertEqual(set(kinds), {"level_up"})

    def test_getting_hurt_is_reported(self):
        game = new_game()
        enemy = self.make_touching(game)
        run(game, 0.2)
        self.assertIn("hurt", self.kinds(game))
        self.assertEqual(game.hp,
                         game.data["hero"]["hp"] - enemy.damage)

    def make_touching(self, game):
        no_spawns(game)
        still_and_tough(game)
        game.weapons = {}
        game.enemies = [game.make_enemy("bat", 0)]
        return game.enemies[0]

    def test_losing_is_reported_once(self):
        game = new_game()
        self.make_touching(game)
        game.hp = 1
        run(game, 0.2)
        self.assertEqual(self.kinds(game)[-1], "lose")
        run(game, 1.0)
        self.assertNotIn("lose", self.kinds(game))

    def test_surviving_to_the_end_is_reported(self):
        game = new_game()
        no_spawns(game)
        tough_hero(game)
        game.data["goal_time"] = 0.2
        run(game, 0.5)
        self.assertTrue(game.won)
        self.assertEqual(self.kinds(game)[-1], "win")

    def test_take_events_clears_the_list(self):
        game = new_game()
        game.add_event("hit", 1.0, 2.0, 3.0)
        self.assertEqual(len(game.take_events()), 1)
        self.assertEqual(game.take_events(), [])

    def test_a_restart_forgets_the_events(self):
        game = new_game()
        game.add_event("hurt", 0.0, 0.0, 5.0)
        game.reset()
        self.assertEqual(game.take_events(), [])


if __name__ == "__main__":
    unittest.main()
