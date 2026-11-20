from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestSaleReportCurrency(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.extra_currency = cls.setup_other_currency("EUR", rates=[("2017-01-01", 0.5)])
        cls.extra_currency.action_create_fields()
        cls.amount_field = f"x_amount_currency_{cls.extra_currency.id}"
        cls.currency_field = f"x_currency_id_{cls.extra_currency.id}"
        cls.partner = cls.env["res.partner"].create({"name": "Report Customer"})
        cls.order = cls.env["sale.order"].sudo().create({
            "partner_id": cls.partner.id,
            "order_line": [(0, 0, {
                "product_id": cls.product_a.id,
                "product_uom_qty": 2.0,
                "price_unit": 100.0,
            })],
        })

    def test_report_exposes_converted_amounts(self):
        report = self.env["sale.report"].sudo()
        for name in (self.amount_field, self.currency_field):
            self.assertIn(name, report._fields)
        line = self.order.order_line
        rows = report.search_read(
            [("order_reference", "=", f"sale.order,{self.order.id}")],
            [self.amount_field, self.currency_field],
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNotNone(row[self.amount_field])
            self.assertEqual(
                row[self.amount_field],
                line[self.amount_field],
            )
            self.assertTrue(row[self.amount_field])
            self.assertEqual(row[self.currency_field][0], self.extra_currency.id)
