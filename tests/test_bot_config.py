import unittest
from bot import requested_permissions, intents, build_invite_url

class TestBotConfig(unittest.TestCase):
    def test_permissions(self):
        self.assertTrue(requested_permissions.ban_members)
        self.assertTrue(requested_permissions.manage_messages)
        self.assertFalse(requested_permissions.manage_roles)

        # Removed permissions must be False
        self.assertFalse(requested_permissions.view_audit_log)
        self.assertFalse(requested_permissions.change_nickname)
        self.assertFalse(requested_permissions.use_external_stickers)
        self.assertFalse(requested_permissions.add_reactions)

        # Kept permissions must be True
        self.assertTrue(requested_permissions.attach_files)
        self.assertTrue(requested_permissions.embed_links)
        self.assertTrue(requested_permissions.send_messages)
        self.assertTrue(requested_permissions.send_messages_in_threads)
        self.assertTrue(requested_permissions.use_external_emojis)
        self.assertTrue(requested_permissions.use_application_commands)
        self.assertTrue(requested_permissions.view_channel)

    def test_intents(self):
        self.assertFalse(intents.presences)
        self.assertTrue(intents.members)
        self.assertTrue(intents.message_content)

    def test_build_invite_url(self):
        url = build_invite_url("123")
        self.assertIn(f"permissions={requested_permissions.value}", url)
        self.assertIn("client_id=123", url)

if __name__ == "__main__":
    unittest.main()
