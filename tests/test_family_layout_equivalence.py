import unittest
from unittest.mock import MagicMock
from cogs.family_commands import FamilyCommands

RANDOM_CASES = [{'seed': 0, 'nodes': [1, 3, 4, 5, 8], 'marriages': [(1, 3), (4, 8), (4, 5)], 'children': [(4, 5), (3, 8)], 'positions': {1: (-140.0, 0.0), 3: (140.0, 0.0), 8: (-140.0, 166.0), 4: (140.0, 166.0), 5: (0.0, 332.0)}, 'has_conflict': True}, {'seed': 1, 'nodes': [1, 2, 4], 'marriages': [(1, 2), (1, 2), (2, 4), (1, 4)], 'children': [], 'positions': {1: (-280.0, 0.0), 2: (0.0, 0.0), 4: (280.0, 0.0)}, 'has_conflict': True}, {'seed': 3, 'nodes': [1, 2, 3, 4, 5], 'marriages': [(2, 5), (3, 4), (1, 5), (1, 5)], 'children': [(4, 3), (5, 2), (2, 4), (5, 4), (4, 2), (2, 5)], 'positions': {1: (-140.0, 0.0), 5: (140.0, 0.0), 2: (-140.0, 166.0), 4: (140.0, 166.0), 3: (0.0, 332.0)}, 'has_conflict': True}, {'seed': 4, 'nodes': [1, 2, 4], 'marriages': [(1, 4), (2, 4)], 'children': [], 'positions': {1: (-280.0, 0.0), 4: (0.0, 0.0), 2: (280.0, 0.0)}, 'has_conflict': True}, {'seed': 5, 'nodes': [1, 2, 3, 4, 5, 6], 'marriages': [(5, 6), (1, 4)], 'children': [(2, 1), (2, 1), (3, 4), (2, 4), (5, 1), (5, 2)], 'positions': {2: (-420.0, 0.0), 5: (-140.0, 0.0), 3: (140.0, 0.0), 6: (420.0, 0.0), 1: (-140.0, 166.0), 4: (140.0, 166.0)}, 'has_conflict': True}, {'seed': 6, 'nodes': [1, 2, 3], 'marriages': [(1, 2), (1, 3), (2, 3)], 'children': [(3, 2), (2, 1), (2, 3), (1, 2), (3, 1), (1, 2)], 'positions': {2: (-140.0, 0.0), 3: (140.0, 0.0), 1: (0.0, 166.0)}, 'has_conflict': True}, {'seed': 8, 'nodes': [1, 2, 4], 'marriages': [(2, 4), (1, 2)], 'children': [], 'positions': {1: (-280.0, 0.0), 2: (0.0, 0.0), 4: (280.0, 0.0)}, 'has_conflict': True}, {'seed': 9, 'nodes': [1, 2, 3, 5, 6, 7, 8, 9], 'marriages': [(5, 6), (3, 9), (1, 6), (8, 9)], 'children': [(2, 6), (9, 1), (7, 3), (8, 7)], 'positions': {7: (0.0, 0.0), 9: (-420.0, 166.0), 2: (-140.0, 166.0), 3: (140.0, 166.0), 8: (420.0, 166.0), 1: (-280.0, 332.0), 6: (0.0, 332.0), 5: (280.0, 332.0)}, 'has_conflict': True}, {'seed': 10, 'nodes': [1, 2], 'marriages': [(1, 2), (1, 2), (1, 2)], 'children': [(1, 2), (2, 1), (1, 2), (2, 1), (2, 1)], 'positions': {1: (0.0, 0.0), 2: (0.0, 166.0)}, 'has_conflict': True}, {'seed': 11, 'nodes': [1, 2, 3, 4, 5, 7, 8, 9], 'marriages': [(8, 9), (4, 9), (3, 8), (2, 3)], 'children': [(5, 3), (2, 1), (7, 8)], 'positions': {5: (-140.0, 0.0), 7: (140.0, 0.0), 2: (-560.0, 166.0), 3: (-280.0, 166.0), 8: (0.0, 166.0), 9: (280.0, 166.0), 4: (560.0, 166.0), 1: (0.0, 332.0)}, 'has_conflict': True}, {'seed': 13, 'nodes': [1, 2, 3, 5, 6], 'marriages': [(2, 6), (2, 6)], 'children': [(2, 6), (6, 2), (2, 1), (5, 2), (6, 3)], 'positions': {5: (0.0, 0.0), 2: (0.0, 166.0), 1: (-140.0, 332.0), 6: (140.0, 332.0), 3: (0.0, 498.0)}, 'has_conflict': True}, {'seed': 14, 'nodes': [1, 2, 3], 'marriages': [(1, 3), (2, 3), (1, 2), (2, 3)], 'children': [(2, 3), (2, 1)], 'positions': {2: (0.0, 0.0), 1: (-140.0, 166.0), 3: (140.0, 166.0)}, 'has_conflict': True}, {'seed': 15, 'nodes': [1, 2, 3], 'marriages': [], 'children': [(1, 2), (2, 1), (1, 2), (3, 2)], 'positions': {1: (-140.0, 0.0), 3: (140.0, 0.0), 2: (0.0, 166.0)}, 'has_conflict': True}, {'seed': 16, 'nodes': [1, 2, 3, 4, 6, 7], 'marriages': [(3, 4), (2, 4), (1, 4)], 'children': [(7, 6), (6, 3), (2, 6)], 'positions': {7: (0.0, 0.0), 6: (0.0, 166.0), 1: (-420.0, 332.0), 4: (-140.0, 332.0), 2: (140.0, 332.0), 3: (420.0, 332.0)}, 'has_conflict': True}, {'seed': 18, 'nodes': [1, 2, 3, 4], 'marriages': [], 'children': [(4, 2), (2, 1), (4, 3), (4, 1), (4, 2)], 'positions': {2: (-140.0, 0.0), 4: (140.0, 0.0), 1: (-140.0, 166.0), 3: (140.0, 166.0)}, 'has_conflict': True}, {'seed': 19, 'nodes': [1, 2], 'marriages': [(1, 2), (1, 2), (1, 2), (1, 2)], 'children': [(2, 1), (2, 1)], 'positions': {2: (0.0, 0.0), 1: (0.0, 166.0)}, 'has_conflict': True}, {'seed': 20, 'nodes': [1, 2, 3, 4], 'marriages': [(1, 2), (1, 2)], 'children': [(4, 1), (1, 4), (3, 2)], 'positions': {4: (-140.0, 0.0), 3: (140.0, 0.0), 1: (-140.0, 166.0), 2: (140.0, 166.0)}, 'has_conflict': True}, {'seed': 21, 'nodes': [1, 2, 3, 4], 'marriages': [(3, 4), (2, 3), (2, 4)], 'children': [(2, 3), (2, 1), (1, 2), (4, 1), (2, 1), (2, 3)], 'positions': {2: (-140.0, 0.0), 4: (140.0, 0.0), 1: (-140.0, 166.0), 3: (140.0, 166.0)}, 'has_conflict': True}, {'seed': 22, 'nodes': [1, 2, 3], 'marriages': [(1, 3)], 'children': [(2, 3), (1, 3), (3, 1)], 'positions': {1: (-140.0, 0.0), 2: (140.0, 0.0), 3: (0.0, 166.0)}, 'has_conflict': True}, {'seed': 24, 'nodes': [1, 2, 3, 4, 5, 6, 7, 8], 'marriages': [(2, 3), (2, 3), (3, 6), (2, 6)], 'children': [(3, 7), (5, 6), (1, 4), (8, 7), (2, 1), (3, 4)], 'positions': {5: (0.0, 0.0), 2: (-140.0, 166.0), 6: (140.0, 166.0), 1: (-280.0, 332.0), 3: (0.0, 332.0), 8: (280.0, 332.0), 4: (-140.0, 498.0), 7: (140.0, 498.0)}, 'has_conflict': True}, {'seed': 30, 'nodes': [1, 3, 4, 7, 10], 'marriages': [(1, 10), (4, 10)], 'children': [(1, 7), (7, 3)], 'positions': {1: (-280.0, 0.0), 10: (0.0, 0.0), 4: (280.0, 0.0), 7: (0.0, 166.0), 3: (0.0, 332.0)}, 'has_conflict': True}, {'seed': 31, 'nodes': [1, 2], 'marriages': [(1, 2), (1, 2), (1, 2)], 'children': [(1, 2), (1, 2), (1, 2), (1, 2)], 'positions': {1: (0.0, 0.0), 2: (0.0, 166.0)}, 'has_conflict': True}, {'seed': 32, 'nodes': [1, 2, 3], 'marriages': [(1, 2)], 'children': [(1, 2), (1, 3), (1, 2), (3, 2), (1, 2)], 'positions': {1: (0.0, 0.0), 2: (-140.0, 166.0), 3: (140.0, 166.0)}, 'has_conflict': True}, {'seed': 33, 'nodes': [1, 2, 3, 4], 'marriages': [(2, 3)], 'children': [(2, 3), (3, 4), (4, 2), (3, 4), (1, 2)], 'positions': {1: (-140.0, 0.0), 4: (140.0, 0.0), 2: (0.0, 166.0), 3: (0.0, 332.0)}, 'has_conflict': True}, {'seed': 34, 'nodes': [1, 4, 10], 'marriages': [(1, 10), (1, 4)], 'children': [], 'positions': {1: (-280.0, 0.0), 4: (0.0, 0.0), 10: (280.0, 0.0)}, 'has_conflict': True}, {'seed': 35, 'nodes': [1, 2, 3, 5, 6, 9], 'marriages': [(3, 6), (3, 5)], 'children': [(5, 1), (9, 5), (6, 2)], 'positions': {9: (0.0, 0.0), 5: (-280.0, 166.0), 3: (0.0, 166.0), 6: (280.0, 166.0), 1: (-140.0, 332.0), 2: (140.0, 332.0)}, 'has_conflict': True}, {'seed': 37, 'nodes': [1, 2, 3], 'marriages': [(1, 3), (2, 3), (1, 2), (2, 3)], 'children': [(2, 3), (3, 2), (2, 1), (1, 3)], 'positions': {2: (0.0, 0.0), 1: (0.0, 166.0), 3: (0.0, 332.0)}, 'has_conflict': True}, {'seed': 39, 'nodes': [1, 2, 3, 4, 5], 'marriages': [(1, 4), (2, 5)], 'children': [(5, 1), (3, 5), (2, 1)], 'positions': {3: (0.0, 0.0), 2: (-140.0, 166.0), 5: (140.0, 166.0), 1: (-140.0, 332.0), 4: (140.0, 332.0)}, 'has_conflict': True}, {'seed': 2, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}, {'seed': 7, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}, {'seed': 12, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}, {'seed': 17, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}, {'seed': 23, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}, {'seed': 25, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}, {'seed': 26, 'nodes': [1, 4], 'marriages': [(1, 4)], 'children': [(4, 1)], 'positions': {4: (0.0, 0.0), 1: (0.0, 166.0)}, 'has_conflict': False}, {'seed': 27, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}, {'seed': 28, 'nodes': [1, 2, 3], 'marriages': [(1, 3)], 'children': [(1, 2)], 'positions': {1: (-140.0, 0.0), 3: (140.0, 0.0), 2: (0.0, 166.0)}, 'has_conflict': False}, {'seed': 29, 'nodes': [1], 'marriages': [], 'children': [], 'positions': {1: (0.0, 0.0)}, 'has_conflict': False}]

VALID_FAMILIES = [('V1_nuclear', 10, {10, 11, 12, 13}, [(10, 11)], [(10, 12), (10, 13)], {10: (-140.0, 0.0), 11: (140.0, 0.0), 12: (-140.0, 166.0), 13: (140.0, 166.0)}), ('V2_three_generations', 20, {20, 21, 22, 23, 24, 25}, [(20, 23)], [(22, 21), (21, 20), (20, 24), (24, 25)], {22: (0.0, 0.0), 21: (0.0, 166.0), 20: (-140.0, 332.0), 23: (140.0, 332.0), 24: (0.0, 498.0), 25: (0.0, 664.0)}), ('V3_target_child', 30, {32, 33, 30, 31}, [(31, 32)], [(31, 30), (31, 33)], {31: (-140.0, 0.0), 32: (140.0, 0.0), 30: (-140.0, 166.0), 33: (140.0, 166.0)}), ('V4_single_person', 40, {40}, [], [], {40: (0.0, 0.0)}), ('V5_two_marriages', 50, {50, 51, 52, 53, 54}, [(50, 51), (52, 53)], [(52, 50), (54, 51)], {52: (-280.0, 0.0), 53: (0.0, 0.0), 54: (280.0, 0.0), 50: (-140.0, 166.0), 51: (140.0, 166.0)})]

class TestFamilyLayoutEquivalence(unittest.TestCase):
    def test_random_graphs_match_original_layout(self):
        cog = FamilyCommands(MagicMock())
        for case in RANDOM_CASES:
            with self.subTest(seed=case["seed"]):
                nodes = set(case["nodes"])
                marriages = [tuple(e) for e in case["marriages"]]
                children = [tuple(e) for e in case["children"]]
                expected = {k: tuple(v) for k, v in case["positions"].items()}
                actual = cog._layout_family_tree(1, nodes, marriages, children)
                self.assertEqual(actual, expected)

    def test_valid_families_match_original_layout(self):
        cog = FamilyCommands(MagicMock())
        for name, target_id, nodes_list, mar_list, chi_list, pos_dict in VALID_FAMILIES:
            with self.subTest(family=name):
                nodes = set(nodes_list)
                marriages = [tuple(e) for e in mar_list]
                children = [tuple(e) for e in chi_list]
                expected = {k: tuple(v) for k, v in pos_dict.items()}
                actual = cog._layout_family_tree(target_id, nodes, marriages, children)
                self.assertEqual(actual, expected)

    def test_valid_families_are_actually_valid(self):
        def check_validity(target_id, nodes, marriages, children):
            # every child appears as a child once (no multiple parents)
            parent_counts = {}
            for p, c in children:
                parent_counts[c] = parent_counts.get(c, 0) + 1
                if parent_counts[c] > 1:
                    return False
            # every person in at most one marriage
            marriage_counts = {}
            for s1, s2 in marriages:
                marriage_counts[s1] = marriage_counts.get(s1, 0) + 1
                marriage_counts[s2] = marriage_counts.get(s2, 0) + 1
                if marriage_counts[s1] > 1 or marriage_counts[s2] > 1:
                    return False
            # no spouse-parent overlap (marriage pair is also parent-child pair)
            mar_set = set(marriages) | {(s2, s1) for s1, s2 in marriages}
            chi_set = set(children)
            if mar_set & chi_set:
                return False
            return True

        for name, target_id, nodes_list, mar_list, chi_list, _ in VALID_FAMILIES:
            self.assertTrue(check_validity(target_id, set(nodes_list), mar_list, chi_list), f"Family {name} should be valid")

        # Positive control: invalid case (child with two parents)
        invalid_children = [(1, 10), (2, 10)]
        self.assertFalse(check_validity(10, {1, 2, 10}, [], invalid_children))

    def test_embedded_random_set_covers_conflict_cases(self):
        conflict_cases = [c for c in RANDOM_CASES if c["has_conflict"] or c["seed"] == 3]
        non_conflict_cases = [c for c in RANDOM_CASES if not c["has_conflict"] and c["seed"] != 3]
        self.assertGreaterEqual(len(conflict_cases), 5)
        self.assertGreaterEqual(len(non_conflict_cases), 5)

if __name__ == "__main__":
    unittest.main()
