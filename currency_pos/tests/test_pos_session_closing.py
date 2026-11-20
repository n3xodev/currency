from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon

@tagged("post_install", "-at_install", "currency_pos")
class TestPosSessionClosing(TestPosPaymentCurrencyCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Account = cls.env["account.account"]
        cls.outstanding_receipts = Account.create(
            {
                "name": "Outstanding Receipts POS",
                "code": "RTPR01",
                "account_type": "asset_current",
                "reconcile": True,
            }
        )
        cls.outstanding_payments = Account.create(
            {
                "name": "Outstanding Payments POS",
                "code": "RTPP01",
                "account_type": "asset_current",
                "reconcile": True,
            }
        )

    def _pay_order(self, payments):
        """Sync an order of `product_mc` (100.00) paid with `payments` [(method, amount)]."""
        order_data = self.create_ui_order_data(
            [(self.product_mc, 1)],
            payments=payments,
        )
        return self.env["pos.order"].sync_from_ui([order_data])

    def test_session_close_with_foreign_bank_payment(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._pay_order([(self.eur_bank_payment_method, 100.0)])
        payment = session.order_ids.payment_ids.filtered(
            lambda pay: pay.payment_method_id == self.eur_bank_payment_method
        )
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.payment_currency_id, self.eur_currency)
        self.assertGreater(payment.payment_currency_amount, 0.0)
        # The core 20 fields the session closing reads follow the payment currency.
        self.assertEqual(payment.foreign_currency_id, self.eur_currency)
        self.assertAlmostEqual(
            payment.amount_currency, payment.payment_currency_amount, places=2
        )
        session.close_session_from_ui({self.cash_payment_method.id: 0.0})
        self.assertEqual(session.state, "closed")
        account_payment = self.env["account.payment"].search(
            [("pos_session_id", "=", session.id)]
        )
        self.assertEqual(account_payment.currency_id, self.eur_currency)
        self.assertAlmostEqual(
            account_payment.amount, payment.payment_currency_amount, places=2
        )

    def test_session_close_with_foreign_cash_payment(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._pay_order([(self.eur_cash_payment_method, 100.0)])
        payment = session.order_ids.payment_ids.filtered(
            lambda pay: pay.payment_method_id == self.eur_cash_payment_method
        )
        closing_data = session.get_closing_control_data()
        eur_cash = next(
            item
            for item in closing_data["default_cash_details"]["cash_details"]
            if item["id"] == self.eur_cash_payment_method.id
        )
        session.close_session_from_ui(
            {
                self.cash_payment_method.id: 0.0,
                self.eur_cash_payment_method.id: eur_cash["amount"],
            }
        )
        self.assertEqual(session.state, "closed")
        eur_box = session._oca_get_cash_box(self.eur_cash_payment_method)
        self.assertAlmostEqual(
            eur_box.balance_end_real, payment.payment_currency_amount, places=2
        )
        self.assertAlmostEqual(eur_box.closing_difference, 0.0, places=2)
        # The cash line is in the journal currency (EUR) and keeps the order amount.
        statement_line = session._oca_statement_lines(self.eur_cash_journal)
        self.assertEqual(len(statement_line), 1)
        self.assertAlmostEqual(
            statement_line.amount, payment.payment_currency_amount, places=2
        )
        self.assertEqual(statement_line.foreign_currency_id, self.usd_currency)
        self.assertAlmostEqual(statement_line.amount_currency, 100.0, places=2)
        # The session receipt is fully reconciled with the cash line.
        term_lines = session.move_ids.line_ids.filtered(
            lambda line: line.display_type == "payment_term"
        )
        self.assertTrue(term_lines)
        self.assertTrue(all(line.reconciled for line in term_lines))

    def test_two_cash_boxes_in_the_same_session(self):
        """Core 20 refuses two cash methods in a session; every box is one here."""
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._pay_order(
            [
                (self.cash_payment_method, 50.0),
                (self.eur_cash_payment_method, 50.0),
            ]
        )
        session.close_session_from_ui(
            {
                self.cash_payment_method.id: 50.0,
                self.eur_cash_payment_method.id: 100.0,
            }
        )
        self.assertEqual(session.state, "closed")
        self.assertAlmostEqual(
            session._oca_statement_lines(self.eur_cash_journal).amount, 100.0, places=2
        )
        term_lines = session.move_ids.line_ids.filtered(
            lambda line: line.display_type == "payment_term"
        )
        self.assertTrue(all(line.reconciled for line in term_lines))

    def test_bank_payment_outstanding_follows_inbound_outbound_lines(self):
        inbound = self.eur_bank_journal.inbound_payment_method_line_ids[:1]
        outbound = self.eur_bank_journal.outbound_payment_method_line_ids[:1]
        inbound.payment_account_id = self.outstanding_receipts
        outbound.payment_account_id = self.outstanding_payments
        wrong_outstanding = self.company_data["default_account_receivable"]
        self.eur_bank_payment_method.write(
            {
                "outstanding_account_id": wrong_outstanding.id,
                "inbound_payment_method_line_id": inbound.id,
                "outbound_payment_method_line_id": outbound.id,
            }
        )
        self.assertEqual(
            self.eur_bank_payment_method._oca_get_payment_outstanding_account_for_amount(
                50.0
            ),
            self.outstanding_receipts,
        )
        self.assertEqual(
            self.eur_bank_payment_method._oca_get_payment_outstanding_account_for_amount(
                -50.0
            ),
            self.outstanding_payments,
        )

        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self.assertEqual(
            self.eur_bank_payment_method.outstanding_account_id,
            wrong_outstanding,
        )

        order_data = self.create_ui_order_data(
            [(self.product_mc, 1)],
            payments=[(self.eur_bank_payment_method, 100.0)],
        )
        self.env["pos.order"].sync_from_ui([order_data])
        session.close_session_from_ui({self.cash_payment_method.id: 0.0})
        self.assertEqual(session.state, "closed")
        inbound_pay = self.env["account.payment"].search(
            [
                ("pos_session_id", "=", session.id),
                ("payment_type", "=", "inbound"),
            ]
        )
        self.assertTrue(inbound_pay)
        self.assertEqual(
            inbound_pay.force_outstanding_account_id,
            self.outstanding_receipts,
        )
        self.assertEqual(
            self.eur_bank_payment_method.outstanding_account_id,
            wrong_outstanding,
        )

    def test_bank_refund_uses_outbound_outstanding_account(self):
        outbound = self.eur_bank_journal.outbound_payment_method_line_ids[:1]
        inbound = self.eur_bank_journal.inbound_payment_method_line_ids[:1]
        inbound.payment_account_id = self.outstanding_receipts
        outbound.payment_account_id = self.outstanding_payments
        self.eur_bank_payment_method.write(
            {
                "outstanding_account_id": self.company_data["default_account_receivable"].id,
                "inbound_payment_method_line_id": inbound.id,
                "outbound_payment_method_line_id": outbound.id,
            }
        )
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        order_data = self.create_ui_order_data(
            [(self.product_mc, -1)],
            payments=[(self.eur_bank_payment_method, -100.0)],
        )
        self.env["pos.order"].sync_from_ui([order_data])
        session.close_session_from_ui({self.cash_payment_method.id: 0.0})
        self.assertEqual(session.state, "closed")
        outbound_pay = self.env["account.payment"].search(
            [
                ("pos_session_id", "=", session.id),
                ("payment_type", "=", "outbound"),
            ]
        )
        self.assertEqual(len(outbound_pay), 1)
        self.assertEqual(outbound_pay.force_outstanding_account_id, self.outstanding_payments)
        self.assertEqual(outbound_pay.currency_id, self.eur_currency)
