# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import date, timedelta

from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestSameDayRate(AccountTestInvoicingCommon):
    """A rate dated D applies on day D (Odoo 19 semantics, ``name <= date``).

    Core Odoo 20 uses ``name < date`` in ``res.currency._get_rates`` so, without
    the override of this module, day D would resolve to the rate of D-1.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.company_currency = cls.company.currency_id
        cls.foreign = cls.env.ref("base.CHF")
        if cls.foreign == cls.company_currency:
            cls.foreign = cls.env.ref("base.EUR")
        cls.env["res.currency.rate"].search([]).unlink()
        cls.foreign.active = True

        cls.day = date(2025, 6, 15)
        cls.rates = {
            cls.day - timedelta(days=2): 2.0,
            cls.day - timedelta(days=1): 4.0,
            cls.day: 8.0,
            cls.day + timedelta(days=1): 16.0,
        }
        cls.rate_records = {}
        for rate_date, rate in cls.rates.items():
            cls.rate_records[rate_date] = cls.env["res.currency.rate"].create(
                {
                    "name": rate_date,
                    "currency_id": cls.foreign.id,
                    "rate": rate,
                    "company_id": cls.company.id,
                }
            )

    def _rate_on(self, day, company=None):
        company = company or self.company
        return self.env["res.currency"]._get_conversion_rate(
            self.company_currency, self.foreign, company, day
        )

    def test_get_conversion_rate_same_day(self):
        self.assertAlmostEqual(self._rate_on(self.day), 8.0)
        self.assertAlmostEqual(self._rate_on(self.day - timedelta(days=1)), 4.0)
        self.assertAlmostEqual(self._rate_on(self.day - timedelta(days=2)), 2.0)

    def test_convert_same_day(self):
        convert = self.company_currency._convert
        self.assertAlmostEqual(
            convert(100.0, self.foreign, self.company, self.day), 800.0
        )
        self.assertAlmostEqual(
            convert(100.0, self.foreign, self.company, self.day - timedelta(days=1)),
            400.0,
        )

    def test_earliest_rate_fallback(self):
        before_first = self.day - timedelta(days=30)
        self.assertAlmostEqual(self._rate_on(before_first), 2.0)
        rates = self.env["res.currency"]._get_rates(self.company, before_first)
        self.assertEqual(rates[self.foreign.id], (2.0, self.day - timedelta(days=2)))

    def test_computed_rate_fields_with_context_date(self):
        currency = self.foreign.with_company(self.company)
        for day, expected in (
            (self.day, 8.0),
            (self.day - timedelta(days=1), 4.0),
        ):
            cur = currency.with_context(
                date=day, to_currency=self.company_currency.id
            )
            self.assertAlmostEqual(cur.rate, expected)
            self.assertAlmostEqual(cur.inverse_rate, 1 / expected)
            self.assertEqual(cur.rate_date, day)

    def test_string_date_in_context(self):
        cur = self.foreign.with_company(self.company).with_context(
            date=fields.Date.to_string(self.day),
            to_currency=self.company_currency.id,
        )
        self.assertAlmostEqual(cur.rate, 8.0)
        self.assertEqual(cur.rate_date, self.day)

    def test_get_rates_accepts_string_date(self):
        rates = self.env["res.currency"]._get_rates(self.company, self.day.isoformat())
        self.assertEqual(rates[self.foreign.id], (8.0, self.day))

    def test_branch_company_uses_root_rates(self):
        branch = self.env["res.company"].create(
            {
                "name": "Branch",
                "parent_id": self.company.id,
                "currency_id": self.company_currency.id,
            }
        )
        self.assertAlmostEqual(self._rate_on(self.day, company=branch), 8.0)
        self.assertAlmostEqual(
            self._rate_on(self.day - timedelta(days=1), company=branch), 4.0
        )

    def test_invoice_uses_rate_of_invoice_date(self):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "company_id": self.company.id,
                "partner_id": self.partner_a.id,
                "invoice_date": self.day,
                "currency_id": self.foreign.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "line",
                            "quantity": 1,
                            "price_unit": 800.0,
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                        }
                    )
                ],
            }
        )
        self.assertAlmostEqual(invoice.invoice_currency_rate, 8.0)
        invoice.action_post()
        self.assertAlmostEqual(invoice.amount_total_signed, 100.0)
        receivable = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        self.assertAlmostEqual(receivable.balance, 100.0)

    def test_move_get_currency_rate_no_double_shift(self):
        move = self.env["account.move"]
        for day, expected in (
            (self.day, 8.0),
            (self.day - timedelta(days=1), 4.0),
        ):
            rate = move.get_currency_rate(
                self.company.id, self.foreign.id, day.isoformat()
            )
            self.assertAlmostEqual(rate, expected)

    def test_cache_distinguishes_dates_and_is_invalidated(self):
        currency = self.env["res.currency"]
        first = currency._get_rates(self.company, self.day)
        second = currency._get_rates(self.company, self.day + timedelta(days=1))
        self.assertEqual(first[self.foreign.id][0], 8.0)
        self.assertEqual(second[self.foreign.id][0], 16.0)
        # same key again hits the cache and stays consistent
        self.assertEqual(currency._get_rates(self.company, self.day), first)
        # writing and creating rates invalidate the cache
        self.rate_records[self.day].rate = 10.0
        rate = currency._get_rates(self.company, self.day)[self.foreign.id][0]
        self.assertEqual(rate, 10.0)
        self.env["res.currency.rate"].create(
            {
                "name": self.day + timedelta(days=2),
                "currency_id": self.foreign.id,
                "rate": 32.0,
                "company_id": self.company.id,
            }
        )
        rates = currency._get_rates(self.company, self.day + timedelta(days=2))
        self.assertEqual(rates[self.foreign.id][0], 32.0)
