from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon


@tagged("post_install", "-at_install", "currency_pos")
class TestPosOrderReceiptCurrency(TestPosPaymentCurrencyCommon):
    """Receipt data of Odoo 20 (`pos.order.receipt`) for payments in a foreign currency."""

    def _order(self, payments):
        self.config = self.multi_currency_config
        self.open_new_session(0)
        order_data = self.create_ui_order_data([(self.product_mc, 1)], payments=payments)
        result = self.env["pos.order"].sync_from_ui([order_data])
        return self.env["pos.order"].browse(result["pos.order"][0]["id"])

    def _fmt(self, amount, currency):
        return currency.format(amount).replace("\xa0", " ")

    def _payment_lines(self, order):
        return {
            payment["payment_method_data"]["name"]: payment
            for payment in order.order_receipt_generate_data()["payments"]
        }

    def test_foreign_payment_shows_its_currency_and_the_order_amount(self):
        order = self._order([(self.eur_bank_payment_method, 100.0)])
        line = self._payment_lines(order)[self.eur_bank_payment_method.name]
        # 100.00 USD at 2.0 EUR per USD.
        self.assertEqual(line["amount"], self._fmt(200.0, self.eur_currency))
        self.assertEqual(line["amount_order_currency"], self._fmt(100.0, self.usd_currency))

    def test_payment_in_the_order_currency_has_no_order_amount(self):
        order = self._order(
            [
                (self.cash_payment_method, 40.0),
                (self.eur_bank_payment_method, 60.0),
            ]
        )
        lines = self._payment_lines(order)
        cash = lines[self.cash_payment_method.name]
        self.assertEqual(cash["amount"], self._fmt(40.0, self.usd_currency))
        self.assertFalse(cash["amount_order_currency"])
        bank = lines[self.eur_bank_payment_method.name]
        self.assertEqual(bank["amount"], self._fmt(120.0, self.eur_currency))
        self.assertEqual(bank["amount_order_currency"], self._fmt(60.0, self.usd_currency))

    def test_foreign_cash_box_payment_is_shown_in_the_box_currency(self):
        order = self._order([(self.eur_cash_payment_method, 100.0)])
        line = self._payment_lines(order)[self.eur_cash_payment_method.name]
        self.assertEqual(line["amount"], self._fmt(200.0, self.eur_currency))
        self.assertEqual(line["amount_order_currency"], self._fmt(100.0, self.usd_currency))

    def test_receipt_html_prints_both_amounts(self):
        order = self._order([(self.eur_bank_payment_method, 100.0)])
        html = str(order.order_receipt_generate_html())
        self.assertIn(self._fmt(200.0, self.eur_currency), html)
        self.assertIn(f"({self._fmt(100.0, self.usd_currency)})", html)

    def test_receipt_html_of_an_order_in_the_order_currency_is_unchanged(self):
        order = self._order([(self.cash_payment_method, 100.0)])
        html = str(order.order_receipt_generate_html())
        self.assertIn(self._fmt(100.0, self.usd_currency), html)
        self.assertNotIn(f"({self._fmt(100.0, self.usd_currency)})", html)

    def test_foreign_payment_is_not_decorated_when_the_config_disallows_it(self):
        # The POS client only treats a payment as foreign when the config allows
        # multi-currency payments; the server data must follow the same rule.
        order = self._order([(self.eur_bank_payment_method, 100.0)])
        self.assertTrue(order.payment_ids.is_foreign_currency_payment)
        # _write skips the config constraint that forbids this with a foreign method.
        order.config_id._write({"allow_multi_currency_payment": False})
        order.config_id.invalidate_recordset(["allow_multi_currency_payment"])
        line = self._payment_lines(order)[self.eur_bank_payment_method.name]
        self.assertFalse(line["amount_order_currency"])
        html = str(order.order_receipt_generate_html())
        self.assertNotIn(f"({self._fmt(100.0, self.usd_currency)})", html)
