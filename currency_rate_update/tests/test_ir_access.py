# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestProviderAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(
            cls.env, "rate_provider_mgr", groups="account.group_account_manager"
        )
        cls.basic = new_test_user(cls.env, "rate_provider_basic")

    def _access(self, user):
        provider = self.env["res.currency.rate.provider"].with_user(user)
        return {op: provider.has_access(op) for op in ("read", "write", "unlink")}

    def test_account_manager_reads_but_cannot_write(self):
        self.assertEqual(
            self._access(self.manager),
            {"read": True, "write": False, "unlink": False},
        )

    def test_settings_admin_has_full_access(self):
        admin = new_test_user(self.env, "rate_provider_sys", groups="base.group_system")
        self.assertEqual(
            self._access(admin), {"read": True, "write": True, "unlink": True}
        )

    def test_internal_user_has_no_access(self):
        self.assertFalse(self._access(self.basic)["read"])
