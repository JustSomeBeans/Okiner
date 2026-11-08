import datetime
import unittest
from unittest.mock import MagicMock
import discord
from alt_detector import calculate_alt_score, FACTOR_LABELS

class TestAltDetector(unittest.TestCase):
    def test_status_removed_and_scoring(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # 1. 400 days old member (expected age score +1, total +1)
        member = MagicMock(spec=discord.Member)
        member.created_at = now - datetime.timedelta(days=400)
        member.name = "alice"
        member.avatar = None
        member.guild_avatar = None
        member.banner = None
        member.premium_since = None
        member.public_flags = MagicMock(active_developer=False, early_supporter=False, verified_bot_developer=False)

        result = calculate_alt_score(member)
        self.assertNotIn("status", result["categories"])
        self.assertNotIn("status", FACTOR_LABELS)
        self.assertEqual(sum(v for v in result["categories"].values() if isinstance(v, int)), result["total"])
        self.assertEqual(result["total"], 1) # age 400d gives +1

        # 2. Same member with status = discord.Status.online must give identical total
        member.status = discord.Status.online
        result_online = calculate_alt_score(member)
        self.assertEqual(result_online["total"], result["total"])

        # 3. Account 2 days old -> age factor -6
        young_member = MagicMock(spec=discord.Member)
        young_member.created_at = now - datetime.timedelta(days=2)
        young_member.name = "bob"
        young_member.avatar = None
        young_member.guild_avatar = None
        young_member.banner = None
        young_member.premium_since = None
        young_member.public_flags = MagicMock(active_developer=False, early_supporter=False, verified_bot_developer=False)
        young_res = calculate_alt_score(young_member)
        self.assertEqual(young_res["categories"]["age"], -6)

        # 4. Account 1200 days old -> age factor +4
        old_member = MagicMock(spec=discord.Member)
        old_member.created_at = now - datetime.timedelta(days=1200)
        old_member.name = "charlie"
        old_member.avatar = None
        old_member.guild_avatar = None
        old_member.banner = None
        old_member.premium_since = None
        old_member.public_flags = MagicMock(active_developer=False, early_supporter=False, verified_bot_developer=False)
        old_res = calculate_alt_score(old_member)
        self.assertEqual(old_res["categories"]["age"], 4)

if __name__ == "__main__":
    unittest.main()
