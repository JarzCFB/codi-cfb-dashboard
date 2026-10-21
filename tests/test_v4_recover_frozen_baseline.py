"""V4 frozen baseline recovery must never invent games or outcomes."""
import unittest
from v4_recover_frozen_baseline import recover

def pick(gid="a", margin="4"):
    return {"game_id": gid, "model_version": "v3", "season": "2026",
            "kickoff_utc": "2026-10-24T20:00:00Z",
            "captured_at_utc": "2026-10-23T10:00:00Z",
            "projected_home_margin": margin}

def grade(p, status="settled", actual="7"):
    return dict(p, grading_status=status, actual_home_margin=actual)

class V4BaselineRecoveryTests(unittest.TestCase):
    def test_settled_and_pending(self):
        a, b = pick("a"), pick("b")
        rows = recover([a, b], [grade(a)])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["actual_home_margin"], "7")
        self.assertEqual(rows[1]["source_grading_status"], "pending")
        self.assertEqual(rows[1]["actual_home_margin"], "")

    def test_non_v3_ignored(self):
        a = dict(pick(), model_version="v2")
        self.assertEqual(recover([a], [grade(a)]), [])

    def test_grade_mismatch_fails(self):
        a = pick()
        with self.assertRaisesRegex(ValueError, "differs"):
            recover([a], [grade(dict(a, projected_home_margin="5"))])

    def test_duplicate_frozen_fails(self):
        a = pick()
        with self.assertRaisesRegex(ValueError, "multiple"):
            recover([a, a], [])

    def test_missing_game_id_fails(self):
        a = dict(pick(), game_id="")
        with self.assertRaisesRegex(ValueError, "ID missing"):
            recover([a], [])

    def test_nonfinite_settled_margin_fails(self):
        a = pick()
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            recover([a], [grade(a, actual="nan")])

    def test_post_kickoff_fails(self):
        a = dict(pick(), captured_at_utc="2026-10-25T10:00:00Z")
        with self.assertRaisesRegex(ValueError, "after kickoff"):
            recover([a], [])

if __name__ == "__main__":
    unittest.main()
