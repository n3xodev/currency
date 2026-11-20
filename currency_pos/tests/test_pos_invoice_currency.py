from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon


@tagged("post_install", "-at_install", "currency_pos")
class TestPosInvoiceForeignPayment(TestPosPaymentCurrencyCommon):
    """Invoice an order paid in a foreign currency (core 20 invoicing + the payment mirror).

    Core 20 builds the invoice payments from pos.payment.foreign_currency_id /
    amount_currency, which currency_pos mirrors from its own payment currency
    fields; no pos.order invoicing method is overridden by this module.
    """

    def _invoiced_order(self, payments):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        order_data = self.create_ui_order_data(
            [(self.product_mc, 1)],
            customer=self.partner1,
            is_invoiced=True,
            payments=payments,
        )
        result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(result["pos.order"][0]["id"])
        return session, order

    def _assert_payment_lines(self, invoice, currency, amount_currency, balance):
        """The reconciled payment lines in `currency` add up to the given amounts."""
        pay_lines = invoice.line_ids.matched_credit_ids.credit_move_id.filtered(
            lambda line: line.currency_id == currency
        )
        self.assertTrue(pay_lines, f"no payment line in {currency.name}")
        self.assertAlmostEqual(abs(sum(pay_lines.mapped("amount_currency"))), amount_currency, places=2)
        self.assertAlmostEqual(abs(sum(pay_lines.mapped("balance"))), balance, places=2)

    def test_invoice_of_an_order_paid_with_foreign_bank(self):
        session, order = self._invoiced_order([(self.eur_bank_payment_method, 100.0)])
        invoice = order.account_move
        self.assertTrue(invoice)
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.currency_id, self.usd_currency)
        self.assertAlmostEqual(invoice.amount_total, 100.0, places=2)
        self.assertEqual(invoice.amount_residual, 0.0)
        self.assertIn(invoice.payment_state, ("paid", "in_payment"))
        # The payment is kept in EUR (rate 2.0) next to its order-currency amount.
        payment = order.payment_ids
        self.assertEqual(payment.payment_currency_id, self.eur_currency)
        self.assertAlmostEqual(payment.payment_currency_amount, 200.0, places=2)
        self.assertAlmostEqual(payment.amount, 100.0, places=2)
        self._assert_payment_lines(invoice, self.eur_currency, 200.0, 100.0)
        self.assertEqual(session.state, "opened")

    def test_invoice_of_an_order_paid_with_foreign_cash_box(self):
        session, order = self._invoiced_order([(self.eur_cash_payment_method, 100.0)])
        invoice = order.account_move
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.amount_residual, 0.0)
        self.assertIn(invoice.payment_state, ("paid", "in_payment"))
        # The cash arrived in the EUR box: it is part of its expected balance.
        # The receivable side reconciled with the invoice stays in the order
        # currency; the liquidity side is booked on the EUR cash journal in EUR.
        self._assert_payment_lines(invoice, self.usd_currency, 100.0, 100.0)
        pay_move = invoice.line_ids.matched_credit_ids.credit_move_id.move_id
        self.assertEqual(pay_move.journal_id, self.eur_cash_journal)
        liquidity = pay_move.line_ids.filtered(lambda line: line.currency_id == self.eur_currency)
        self.assertAlmostEqual(abs(sum(liquidity.mapped("amount_currency"))), 200.0, places=2)
        self.assertAlmostEqual(abs(sum(liquidity.mapped("balance"))), 100.0, places=2)
        eur_box = session._oca_get_cash_box(self.eur_cash_payment_method)
        self.assertAlmostEqual(eur_box._oca_get_expected_balance(), 200.0, places=2)

    def test_invoice_of_an_order_paid_in_two_currencies(self):
        _session, order = self._invoiced_order(
            [
                (self.cash_payment_method, 40.0),
                (self.eur_bank_payment_method, 60.0),
            ]
        )
        invoice = order.account_move
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.amount_residual, 0.0)
        eur_payment = order.payment_ids.filtered(
            lambda pay: pay.payment_method_id == self.eur_bank_payment_method
        )
        self.assertAlmostEqual(eur_payment.payment_currency_amount, 120.0, places=2)
        self.assertAlmostEqual(sum(order.payment_ids.mapped("amount")), 100.0, places=2)
        self._assert_payment_lines(invoice, self.eur_currency, 120.0, 60.0)
        self._assert_payment_lines(invoice, self.usd_currency, 40.0, 40.0)

    def test_taxed_order_paid_in_foreign_currency_keeps_tax_in_order_currency(self):
        tax = self.env["account.tax"].create(
            {"name": "POS MC 16%", "amount_type": "percent", "amount": 16.0}
        )
        taxed_product = self.create_product(
            "MC Taxed Product", self.categ_basic, 100.0, tax_ids=tax.ids
        )
        taxed_product.available_in_pos = True
        self.config = self.multi_currency_config
        self.open_new_session(0)
        order_data = self.create_ui_order_data(
            [(taxed_product, 1)],
            customer=self.partner1,
            is_invoiced=True,
            payments=[(self.eur_bank_payment_method, 116.0)],
        )
        result = self.env["pos.order"].sync_from_ui([order_data])
        order = self.env["pos.order"].browse(result["pos.order"][0]["id"])
        invoice = order.account_move
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.currency_id, self.usd_currency)
        self.assertAlmostEqual(invoice.amount_untaxed, 100.0, places=2)
        self.assertAlmostEqual(invoice.amount_tax, 16.0, places=2)
        self.assertAlmostEqual(invoice.amount_total, 116.0, places=2)
        self.assertEqual(invoice.amount_residual, 0.0)
        self.assertAlmostEqual(order.payment_ids.payment_currency_amount, 232.0, places=2)
        self._assert_payment_lines(invoice, self.eur_currency, 232.0, 116.0)
