# Copyright 2026 n3xodev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from lxml import etree

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCurrencyRateLiveGuard(TransactionCase):
    def test_company_interval_forced_manually_on_write(self):
        company = self.env.company
        company.write({
            "currency_interval_unit": "daily",
            "currency_next_execution_date": fields.Date.today(),
        })
        self.assertEqual(company.currency_interval_unit, "manually")
        self.assertFalse(company.currency_next_execution_date)

    def test_company_interval_forced_manually_on_create(self):
        company = self.env["res.company"].create({
            "name": "Test Guard Company",
            "currency_interval_unit": "weekly",
            "currency_next_execution_date": fields.Date.today(),
        })
        self.assertEqual(company.currency_interval_unit, "manually")
        self.assertFalse(company.currency_next_execution_date)

    def test_run_update_currency_is_noop(self):
        with patch.object(
            type(self.env["res.company"]), "update_currency_rates"
        ) as mocked_update:
            res = self.env["res.company"].run_update_currency()
        self.assertFalse(res)
        mocked_update.assert_not_called()

    def test_settings_view_hides_live_block(self):
        view_arch = self.env["res.config.settings"].get_view(view_type="form")["arch"]
        root = etree.fromstring(view_arch)
        self.assertEqual(
            root.xpath("//setting[@id='update_exchange_rates']/@invisible"),
            ["1"],
        )
        self.assertTrue(root.xpath("//field[@name='currency_rates_autoupdate']"))
