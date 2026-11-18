from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountInvoiceReportCurrency(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.extra_currency = cls.setup_other_currency("EUR", rates=[("2017-01-01", 0.5)])
        cls.extra_currency.action_create_fields()
        cls.amount_field = f"x_amount_currency_{cls.extra_currency.id}"
        cls.subtotal_field = f"x_subtotal_currency_{cls.extra_currency.id}"
        cls.currency_field = f"x_currency_id_{cls.extra_currency.id}"

    def test_report_exposes_converted_amounts(self):
        invoice = self.init_invoice(
            "out_invoice", post=True, invoice_date="2019-01-01", amounts=[100.0]
        )
        report = self.env["account.invoice.report"].sudo()
        for name in (self.amount_field, self.subtotal_field, self.currency_field):
            self.assertIn(name, report._fields)
        rows = report.search_read(
            [("move_id", "=", invoice.id)],
            [self.amount_field, self.subtotal_field, self.currency_field],
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(row[self.amount_field])
            self.assertIsNotNone(row[self.subtotal_field])
            self.assertTrue(row[self.amount_field])
            self.assertTrue(row[self.subtotal_field])
            self.assertEqual(row[self.currency_field][0], self.extra_currency.id)
