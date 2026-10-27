"""
Newness 边界行为锁定测试（负责人：陈虹宇 复核）。

背景：Newness 可能存在边界问题（待复核）。在复核得出结论之前，
本文件把当前（legacy）行为用测试锁死 —— 数学代码与旧实验基线
完全一致，任何人在没有说明的情况下都不允许改变这些结果。

如果复核后确认有 bug 并修改了 newness.py：
    1. 先在群里说明，并在提交信息里写清楚影响；
    2. 同步更新本文件的期望值（有意为之的更新，而不是静默变化）；
    3. 旧实验基线结果留在 final/ami_parser，不回头改。
"""

import unittest

import numpy as np

from gca_engine.core.newness import contribution_newness, participant_newness


class TestNewnessLegacyBehaviour(unittest.TestCase):
    """锁定当前 legacy 行为的边界情况。"""

    def test_first_contribution_is_always_1_0(self):
        # 第一条发言没有历史子空间，约定为 1.0（项目约定，非论文规定）
        result = contribution_newness(np.array([[1.0, 0.0]]))
        np.testing.assert_allclose(result, [1.0], atol=1e-12)

    def test_first_contribution_zero_vector_is_0_0(self):
        # 零向量按 zero-vector policy 处理为 0.0（不是 1.0）
        result = contribution_newness(np.array([[0.0, 0.0]]))
        np.testing.assert_allclose(result, [0.0], atol=1e-12)

    def test_identical_to_history_is_0_0(self):
        vectors = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
        result = contribution_newness(vectors)
        np.testing.assert_allclose(result, [1.0, 0.0, 0.0], atol=1e-12)

    def test_scaled_copy_of_history_is_0_0(self):
        # 方向和历史一致（只是长度不同），仍在子空间内 -> 0.0
        vectors = np.array([[1.0, 0.0], [2.0, 0.0]])
        result = contribution_newness(vectors)
        np.testing.assert_allclose(result, [1.0, 0.0], atol=1e-12)

    def test_orthogonal_is_1_0(self):
        vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
        result = contribution_newness(vectors)
        np.testing.assert_allclose(result, [1.0, 1.0], atol=1e-12)

    def test_all_zero_history_gives_1_0(self):
        # 历史全是零向量 -> 子空间为空 -> 1.0
        vectors = np.array([[0.0, 0.0], [1.0, 0.0]])
        result = contribution_newness(vectors)
        np.testing.assert_allclose(result, [0.0, 1.0], atol=1e-12)

    def test_linear_combination_of_history_is_0_0(self):
        # d3 = d1 + d2 在 span(d1, d2) 内 -> 0.0
        vectors = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
        result = contribution_newness(vectors)
        np.testing.assert_allclose(result, [1.0, 1.0, 0.0], atol=1e-10)

    def test_rank_deficient_history(self):
        # 历史三个相同向量（秩 1），再来一个正交向量 -> 1.0
        vectors = np.array(
            [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        )
        result = contribution_newness(vectors)
        np.testing.assert_allclose(result, [1.0, 0.0, 0.0, 1.0], atol=1e-12)

    def test_history_longer_than_dimension(self):
        # 历史向量个数超过维度（2 维空间 4 条历史）
        vectors = np.array(
            [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [-1.0, 0.0], [3.0, -2.0]]
        )
        result = contribution_newness(vectors)
        # 前两条铺满 2 维空间，后面全部在子空间内 -> 0.0
        np.testing.assert_allclose(result, [1.0, 1.0, 0.0, 0.0, 0.0], atol=1e-10)

    def test_paper_formula_half(self):
        # 论文公式 ||n||/(||n||+||g||)：d=[1,1] 在历史 {[1,0]} 上
        # g=[1,0]（norm 1），n=[0,1]（norm 1）-> 0.5
        vectors = np.array([[1.0, 0.0], [1.0, 1.0]])
        result = contribution_newness(vectors)
        np.testing.assert_allclose(result, [1.0, 0.5], atol=1e-12)

    def test_always_in_01(self):
        # 随机输入下结果永远在 [0,1]，且没有 NaN / Inf
        rng = np.random.default_rng(42)
        for seed in range(5):
            rng = np.random.default_rng(seed)
            vectors = rng.normal(size=(12, 8))
            result = contribution_newness(vectors)
            self.assertFalse(np.isnan(result).any())
            self.assertFalse(np.isinf(result).any())
            self.assertTrue((result >= 0.0).all())
            self.assertTrue((result <= 1.0).all())

    def test_deterministic(self):
        rng = np.random.default_rng(7)
        vectors = rng.normal(size=(10, 6))
        r1 = contribution_newness(vectors)
        r2 = contribution_newness(vectors)
        np.testing.assert_array_equal(r1, r2)

    def test_participant_mean(self):
        # 历史行为：按人取平均
        arr = np.array([1.0, 0.0, 0.0, 1.0, 0.0])
        by_speaker = participant_newness(arr, ["A", "A", "B", "A", "C"])
        self.assertAlmostEqual(by_speaker["A"], 2.0 / 3.0)
        self.assertAlmostEqual(by_speaker["B"], 0.0)
        self.assertAlmostEqual(by_speaker["C"], 0.0)


if __name__ == "__main__":
    unittest.main()
