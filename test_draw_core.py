"""draw_core 的单元测试：python -m unittest test_draw_core"""

import json
import os
import random
import tempfile
import unittest
from collections import Counter

from draw_core import (
    ConfigStore,
    DEFAULT_ROUND_SIZE,
    DrawConfig,
    DrawEngine,
    HistoryStore,
    decrypt_history,
    encrypt_history,
    normalize_config,
)


def make_engine(**cfg):
    """在临时目录里建一个引擎，配置写入 config.json。"""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    return DrawEngine(ConfigStore(path), HistoryStore(os.path.join(tmp, "history.json")))


class TestNormalizeConfig(unittest.TestCase):
    def test_non_dict_falls_back_to_defaults(self):
        for bad in (None, [], "abc", 42):
            self.assertEqual(normalize_config(bad), normalize_config({}))

    def test_illegal_fields_fall_back_individually(self):
        cfg = normalize_config({"pool_min": None, "excluded": "x"})
        defaults = normalize_config({})
        self.assertEqual(cfg["pool_min"], defaults["pool_min"])
        self.assertEqual(cfg["excluded"], defaults["excluded"])

    def test_inverted_range_falls_back(self):
        cfg = normalize_config({"pool_min": 54, "pool_max": 1})
        defaults = normalize_config({})
        self.assertEqual((cfg["pool_min"], cfg["pool_max"]), (defaults["pool_min"], defaults["pool_max"]))

    def test_numeric_strings_accepted(self):
        cfg = normalize_config({"excluded": ["37", 39], "pool_min": "1", "pool_max": "10"})
        self.assertEqual(cfg["excluded"], [37, 39])
        self.assertEqual((cfg["pool_min"], cfg["pool_max"]), (1, 10))

    def test_deprecated_reroll_keys_are_dropped(self):
        """已废弃的重抽配置不再生效，也不会写回配置文件。"""
        cfg = normalize_config({"reroll_triggers": [46, 47], "max_rerolls": 10})
        self.assertNotIn("reroll_triggers", cfg)
        self.assertNotIn("max_rerolls", cfg)

    def test_unknown_keys_are_dropped(self):
        self.assertEqual(
            set(normalize_config({"excluded": [], "pool_min": 1, "pool_max": 5, "wtf": 1})),
            {"excluded", "pool_min", "pool_max"},
        )


class TestDrawConfig(unittest.TestCase):
    def test_candidates_exclude_configured_numbers(self):
        cfg = DrawConfig({"pool_min": 1, "pool_max": 10, "excluded": [3, 7]})
        self.assertEqual(cfg.candidates(), [1, 2, 4, 5, 6, 8, 9, 10])

    def test_empty_candidates_when_everything_excluded(self):
        cfg = DrawConfig({"pool_min": 1, "pool_max": 5, "excluded": [1, 2, 3, 4, 5]})
        self.assertEqual(cfg.candidates(), [])


class TestConfigStore(unittest.TestCase):
    def test_creates_default_file_when_missing(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "config.json")
        store = ConfigStore(path)
        self.assertFalse(os.path.exists(path))
        config = store.load()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(config.as_dict(), DrawConfig().as_dict())

    def test_repairs_incomplete_file(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pool_min": 3}, f)

        config = ConfigStore(path).load()
        with open(path, "r", encoding="utf-8") as f:
            written = json.load(f)

        self.assertEqual(set(written), set(config.as_dict()))
        self.assertEqual(written["pool_min"], 3)
        self.assertEqual(written["pool_max"], DrawConfig().pool_max)

    def test_corrupted_file_falls_back_to_defaults(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(ConfigStore(path).load().as_dict(), DrawConfig().as_dict())

    def test_legacy_reroll_keys_removed_from_file(self):
        """旧配置文件里的重抽字段应被清除，避免留下已失效的开关。"""
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"excluded": [1], "reroll_triggers": [46], "max_rerolls": 10,
                       "pool_min": 1, "pool_max": 54}, f)

        ConfigStore(path).load()
        with open(path, "r", encoding="utf-8") as f:
            written = json.load(f)

        self.assertEqual(set(written), {"excluded", "pool_min", "pool_max"})
        self.assertEqual(written["excluded"], [1])


class TestDrawEngine(unittest.TestCase):
    CFG = {"pool_min": 1, "pool_max": 20, "excluded": [20]}

    def test_consumes_exactly_one_per_draw(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        expected = len(DrawConfig(self.CFG).candidates())
        for _ in range(expected):
            self.assertIsNotNone(engine.draw())
            expected -= 1
            self.assertEqual(len(engine.remaining_pool), expected)

    def test_drains_then_reports(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        for _ in range(len(DrawConfig(self.CFG).candidates())):
            engine.draw()
        self.assertIsNone(engine.draw())
        self.assertIn("抽完", engine.last_error)

    def test_only_returns_candidates(self):
        engine = make_engine(**self.CFG)
        candidates = set(DrawConfig(self.CFG).candidates())
        engine.reset_pool()
        for _ in range(len(candidates)):
            self.assertIn(engine.draw(), candidates)

    def test_full_cycle_yields_every_number_exactly_once(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        drawn = sorted(engine.draw() for _ in range(len(DrawConfig(self.CFG).candidates())))
        self.assertEqual(drawn, sorted(DrawConfig(self.CFG).candidates()))

    def test_distribution_is_uniform(self):
        """没有任何加权或排除机制，各号码出现频次应当接近。"""
        pool_size, rounds = 54, 400
        engine = make_engine(pool_min=1, pool_max=pool_size, excluded=[])
        random.seed(20240101)
        counts = [0] * (pool_size + 1)
        for _ in range(rounds):
            engine.reset_pool()
            for _ in range(pool_size):
                counts[engine.draw()] += 1

        expected = rounds * pool_size / pool_size
        deviations = [abs(counts[i] - expected) for i in range(1, pool_size + 1)]
        # 400 轮 × 54 次 = 21600 次抽样，单号标准差约 20，3σ ≈ 60
        self.assertLess(max(deviations), 60, f"分布偏离均匀：{counts}")

    def test_distribution_is_uniform_at_teacher_draw_rate(self):
        """按老师实际频率(每轮 20~30 次，抽完这轮即重置)抽签，分布应当均匀。

        回归：v0.13 有「低爆池」机制，把 8 个号(2/23/43/46/47/49/51/54)从常规池
        里剔除，等常规池抽完才轮到它们。而常规池有 43 个号、每轮只抽 20~30 个，
        这些号永远等不到被抽中的那一轮，实际抽签机会为 0%。
        本用例确保每个候选号在真实频率下都有合理的出现概率。
        """
        rounds = 3000
        cfg = {"pool_min": 1, "pool_max": 54, "excluded": [37, 39, 50, 54]}
        candidates = DrawConfig(cfg).candidates()
        pool_size = len(candidates)

        random.seed(20240101)
        engine = make_engine(**cfg)
        counts = {num: 0 for num in candidates}
        total = 0
        for _ in range(rounds):
            engine.reset_pool()
            # 每轮抽 20~30 个就重置，不抽完整池——这是老师的实际用法
            for _ in range(random.randint(20, 30)):
                counts[engine.draw()] += 1
                total += 1

        expected = total / pool_size
        # 卡方拟合优度：df = pool_size - 1 = 49，p=0.05 临界值约 67.5
        chi2 = sum((counts[i] - expected) ** 2 / expected for i in candidates)
        self.assertLess(chi2, 67.5, f"分布偏离均匀(卡方={chi2:.1f})：{counts}")

        # 最热号与最冷号的频次比，理论应接近 1.0
        observed = list(counts.values())
        self.assertLess(max(observed) / min(observed), 1.5,
                        f"冷热差异过大：最热{max(observed)} 最冷{min(observed)}")

    def test_every_number_reachable_at_teacher_draw_rate(self):
        """按真实频率(每轮 20~30 次，抽完即重置)抽签，每个号都必须有机会出现。

        回归：v0.13 的低爆池机制会让部分号每轮出现率为 0%，普通号却反复出现，
        这正是「总是抽出相同的号」的来源。
        """
        rounds = 2000
        cfg = {"pool_min": 1, "pool_max": 54, "excluded": [37, 39, 50, 54]}
        candidates = DrawConfig(cfg).candidates()

        random.seed(20240101)
        engine = make_engine(**cfg)
        appear_rounds = {num: 0 for num in candidates}
        for _ in range(rounds):
            engine.reset_pool()
            drawn = {engine.draw() for _ in range(random.randint(20, 30))}
            for num in drawn:
                appear_rounds[num] += 1

        # 每轮约抽 25 次 / 50 个号 ≈ 50% 的轮次会出现某个号
        min_rounds = min(appear_rounds.values())
        self.assertGreater(min_rounds / rounds, 0.35,
                           f"有号码出现率过低："
                           f"{ {n: r for n, r in appear_rounds.items() if r == min_rounds} }")
        max_rounds = max(appear_rounds.values())
        self.assertLess(max_rounds / min_rounds, 1.5,
                        f"冷热差异过大：{max_rounds} vs {min_rounds}")

    def test_excluded_numbers_never_drawn(self):
        engine = make_engine(pool_min=1, pool_max=30, excluded=[5, 6, 7])
        engine.reset_pool()
        drawn = {engine.draw() for _ in range(1000) if engine.remaining_pool}
        engine.reset_pool()
        drawn |= {engine.draw() for _ in range(1000)}
        self.assertFalse(drawn & {5, 6, 7})


class TestFairnessWeighting(unittest.TestCase):
    """加权抽签：让被抽得少的号码优先，同时保持随机性。"""

    CFG = {"pool_min": 1, "pool_max": 54, "excluded": [37, 39, 50, 54]}

    def test_counts_survive_pool_reset(self):
        """累计抽签次数跨轮保留，这是加权生效的前提。"""
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        first = engine.draw()
        engine.reset_pool()
        engine.draw()

        self.assertEqual(engine.draw_counts[first], 1)
        self.assertEqual(sum(engine.draw_counts.values()), 2)

    def test_forget_history_clears_counts(self):
        """forget_history=True 应连同累计记录一起清空。"""
        engine = make_engine(**self.CFG)
        for _ in range(5):
            engine.reset_pool()
            engine.draw()
        self.assertTrue(engine.draw_counts)

        engine.reset_pool(forget_history=True)
        self.assertEqual(engine.draw_counts, {})

        engine.reset_pool()
        engine.draw()
        self.assertEqual(len(engine.draw_counts), 1)

    def test_drawn_numbers_get_lower_weight(self):
        """被抽过的号码短期内应比没抽过的更难再被抽中。

        用一个已被抽过多次的号和一个从未被抽的号做对照。
        """
        engine = make_engine(pool_min=1, pool_max=6, excluded=[])
        engine.reset_pool()

        # 手工把 1 号的累计次数拉高，模拟它被反复抽到
        engine.draw_counts = {1: 6}
        engine.remaining_pool = [1, 2, 3, 4, 5, 6]

        # 直接采样 _pick_index，看 1 号被选中的比例
        hits = 0
        trials = 20000
        for _ in range(trials):
            idx = engine._pick_index()
            if engine.remaining_pool[idx] == 1:
                hits += 1

        # 权重 2^-6 = 1/64，池内其余 5 个权重都是 1
        # 理论概率 = (1/64) / (1/64 + 5) = 0.0031
        expected = (1 / 64) / (1 / 64 + 5)
        self.assertLess(hits / trials, expected * 3,
                        f"高频号码仍被过多抽中：{hits}/{trials}")
        self.assertGreater(hits, 0, "被高频抽中的号不应被完全排除")

    def test_raises_barrier_against_two_round_cycle(self):
        """回归：严格轮换会形成两轮循环（每两次抽到完全相同的一批）。

        加权方案必须既降低相邻轮重叠，又不产生周期性。
        """
        cfg = self.CFG
        candidates = DrawConfig(cfg).candidates()
        n = len(candidates)
        rounds = 400
        per_round = n // 2

        random.seed(20240101)
        engine = make_engine(**cfg)
        history = []
        for _ in range(rounds):
            engine.reset_pool()
            history.append({engine.draw() for _ in range(per_round)})

        adjacent = sum(len(history[i] & history[i + 1]) for i in range(rounds - 1)) / (rounds - 1)
        every_two = sum(len(history[i] & history[i + 2]) for i in range(rounds - 2)) / (rounds - 2)

        # 纯随机的理论重叠是 per_round^2 / n
        expected = per_round * per_round / n
        self.assertLess(adjacent, expected * 0.95,
                        f"相邻轮重叠应低于纯随机：{adjacent:.2f} vs {expected:.2f}")
        # 没有周期性：隔两轮的重叠不应塌缩到 0（那是两轮循环的特征）
        self.assertGreater(every_two, expected * 0.5,
                           f"出现两轮循环：隔两轮重叠仅 {every_two:.2f}")

    def test_empty_pool_reports_instead_of_crashing(self):
        engine = make_engine(pool_min=1, pool_max=5, excluded=[1, 2, 3, 4, 5])
        engine.reset_pool()
        self.assertIsNone(engine.draw())
        self.assertIn("抽完", engine.last_error)

    def test_reload_picks_up_config_changes(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        old_pool = sorted(engine.remaining_pool)
        with open(engine.store.path, "w", encoding="utf-8") as f:
            json.dump({"pool_min": 1, "pool_max": 5, "excluded": []}, f)

        engine.reload()

        # reload 只换配置、不动已在用的池子；下一次 reset_pool 才按新配置重建
        self.assertEqual(sorted(engine.remaining_pool), old_pool)
        engine.reset_pool()
        self.assertEqual(sorted(engine.remaining_pool), [1, 2, 3, 4, 5])


class TestHistoryEncryption(unittest.TestCase):
    """累计记录加密存储：文件不落明文、可回读、损坏容错、旧明文迁移。"""

    def _tmp(self):
        tmp = tempfile.mkdtemp()
        return os.path.join(tmp, "history.json")

    def test_encrypt_round_trip(self):
        plain = b'{"1": 5, "2": 3}'
        token = encrypt_history(plain)
        self.assertEqual(decrypt_history(token), plain)

    def test_saved_file_is_not_plaintext(self):
        path = self._tmp()
        store = HistoryStore(path)
        store.save({1: 5, 2: 3})
        raw = json.load(open(path, encoding="utf-8"))
        # 文件应是加密结构（含 ct/mac），明文键值对不直接暴露
        self.assertIn("ct", raw)
        self.assertIn("mac", raw)
        serialized = json.dumps(raw)
        self.assertNotIn('"1": 5', serialized)
        self.assertNotIn('"2": 3', serialized)

    def test_store_save_load_round_trip(self):
        path = self._tmp()
        store = HistoryStore(path)
        store.save({1: 5, 2: 3, 10: 1})
        loaded = store.load(valid_numbers=[1, 2, 3, 4, 5, 10])
        self.assertEqual(loaded, {1: 5, 2: 3, 10: 1})

    def test_load_filters_to_valid_numbers(self):
        path = self._tmp()
        HistoryStore(path).save({1: 5, 99: 7})
        loaded = HistoryStore(path).load(valid_numbers=[1, 2, 3])
        self.assertEqual(loaded, {1: 5})

    def test_corrupted_file_returns_empty(self):
        path = self._tmp()
        with open(path, "w", encoding="utf-8") as f:
            f.write("{{{not json")
        self.assertEqual(HistoryStore(path).load(), {})
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"v": 1, "ct": "AAAA", "mac": "bad"}, f)
        self.assertEqual(HistoryStore(path).load(), {})

    def test_legacy_plaintext_migrates(self):
        """旧版明文 dict 仍可加载（迁移兼容）。"""
        path = self._tmp()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"1": 4, "3": 2}, f)
        self.assertEqual(HistoryStore(path).load(), {1: 4, 3: 2})

    def test_clear_writes_empty(self):
        path = self._tmp()
        store = HistoryStore(path)
        store.save({1: 5})
        store.clear()
        self.assertEqual(HistoryStore(path).load(), {})


class TestRoundIsolation(unittest.TestCase):
    """轮次隔离：上一轮不满 20 抽就重置时，下一轮不抽到上一轮已抽号码。"""

    CFG = {"pool_min": 1, "pool_max": 50, "excluded": []}

    def test_incomplete_round_excludes_previous_drawn(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        drawn = [engine.draw() for _ in range(3)]  # 不满一轮
        engine.reset_pool()
        self.assertFalse(
            set(engine.remaining_pool) & set(drawn),
            f"下一轮不应含上一轮已抽号 {drawn}，实际池 {engine.remaining_pool}",
        )

    def test_full_round_returns_to_full_pool(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        for _ in range(DEFAULT_ROUND_SIZE):
            engine.draw()  # 抽满一轮
        engine.reset_pool()
        self.assertEqual(
            sorted(engine.remaining_pool),
            sorted(DrawConfig(self.CFG).candidates()),
            "抽满一轮后下一轮应恢复全池",
        )

    def test_forget_history_clears_isolation(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        engine.draw()
        engine.reset_pool(forget_history=True)
        self.assertEqual(
            sorted(engine.remaining_pool),
            sorted(DrawConfig(self.CFG).candidates()),
            "彻底重开后应恢复全池",
        )

    def test_round_drawn_tracks_draws(self):
        engine = make_engine(**self.CFG)
        engine.reset_pool()
        a, b = engine.draw(), engine.draw()
        self.assertEqual(engine.round_drawn, [a, b])
        engine.reset_pool()
        self.assertEqual(engine.round_drawn, [])


if __name__ == "__main__":
    unittest.main()