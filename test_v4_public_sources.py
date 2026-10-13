import unittest
from v4_public_sources import public_source_directory

class PublicSourcesTests(unittest.TestCase):
    def test_source_directory_is_explicitly_manual(self):
        sources = public_source_directory()
        self.assertGreaterEqual(len(sources), 3)
        self.assertTrue(all(source["url"].startswith("https://") for source in sources))
        self.assertTrue(all(source["automated"] is False for source in sources))
        self.assertTrue(all("coverage" in source for source in sources))

    def test_registry_does_not_claim_any_player_is_available(self):
        for source in public_source_directory():
            self.assertNotIn("player", source)
            self.assertNotIn("status", source)

if __name__ == "__main__":
    unittest.main()
