from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon


@tagged("post_install", "-at_install", "currency_pos")
class TestPosClosingAccounts(TestPosPaymentCurrencyCommon):
    def _pay_order(self, payments):
        order_data = self.create_ui_order_data([(self.product_mc, 1)], payments=payments)
        return self.env["pos.order"].sync_from_ui([order_data])

    def test_bank_payment_falls_back_to_the_method_outstanding_account(self):
        """A method line without account uses the outstanding account of the
        method, like core, not the chart default."""
        inbound = self.eur_bank_journal.inbound_payment_method_line_ids[:1]
        inbound.payment_account_id = False
        outstanding = self.company_data["default_account_receivable"]
        self.eur_bank_payment_method.write(
            {"outstanding_account_id": outstanding.id, "inbound_payment_method_line_id": inbound.id}
        )
        self.assertEqual(
            self.eur_bank_payment_method._oca_get_payment_outstanding_account_for_amount(50.0),
            outstanding,
        )
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._pay_order([(self.eur_bank_payment_method, 100.0)])
        session.close_session_from_ui({self.cash_payment_method.id: 0.0})
        inbound_pay = self.env["account.payment"].search(
            [("pos_session_id", "=", session.id), ("payment_type", "=", "inbound")]
        )
        self.assertEqual(inbound_pay.force_outstanding_account_id, outstanding)

    def test_core_native_foreign_payment_survives_the_closing(self):
        """A payment created with core's own foreign currency fields is not
        overwritten by this module's mirror and is booked as core does."""
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        order_data = self.create_ui_order_data(
            [(self.product_mc, 1)],
            payments=[(self.cash_payment_method, 100.0)],
        )
        order_data["payment_ids"][0][2].update(
            {"foreign_currency_id": self.eur_currency.id, "amount_currency": 200.0}
        )
        self.env["pos.order"].sync_from_ui([order_data])
        payment = session.order_ids.payment_ids
        self.assertEqual(payment.foreign_currency_id, self.eur_currency)
        self.assertAlmostEqual(payment.amount_currency, 200.0, places=2)
        session.close_session_from_ui({self.cash_payment_method.id: 100.0})
        self.assertEqual(session.state, "closed")
        payment = session.order_ids.payment_ids
        self.assertEqual(payment.foreign_currency_id, self.eur_currency)
        self.assertAlmostEqual(payment.amount_currency, 200.0, places=2)
        statement_line = session._oca_statement_lines(self.cash_payment_method.journal_id)
        self.assertEqual(statement_line.foreign_currency_id, self.eur_currency)
        self.assertAlmostEqual(statement_line.amount_currency, 200.0, places=2)
        self.assertAlmostEqual(statement_line.amount, 100.0, places=2)

    def test_secondary_box_change_is_counted_at_closing(self):
        """The change given back in a foreign box leaves the foreign statement
        line with the net amount the customer really handed over."""
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._pay_order([(self.eur_cash_payment_method, 100.0)])
        order = session.order_ids[:1]
        # The customer hands over 40 EUR more than due and gets them back as change.
        for amount, foreign_amount, is_change in ((20.0, 40.0, False), (-20.0, -40.0, True)):
            order.add_payment(
                {
                    "name": "return" if is_change else "overpayment",
                    "pos_order_id": order.id,
                    "amount": amount,
                    "payment_method_id": self.eur_cash_payment_method.id,
                    "payment_currency_id": self.eur_currency.id,
                    "payment_currency_amount": foreign_amount,
                    "is_change": is_change,
                }
            )
        session.close_session_from_ui(
            {
                str(self.cash_payment_method.id): 0.0,
                str(self.eur_cash_payment_method.id): 200.0,
            }
        )
        self.assertEqual(session.state, "closed")
        box = session._oca_get_cash_box(self.eur_cash_payment_method)
        self.assertAlmostEqual(box.closing_difference, 0.0, places=2)
        self.assertAlmostEqual(
            session._oca_statement_lines(self.eur_cash_journal).amount, 200.0, places=2
        )

    def test_core_foreign_fields_follow_the_module_only_when_it_set_them(self):
        order = self._create_draft_order()
        payment = self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": 0.0,
                "payment_method_id": self.eur_bank_payment_method.id,
                "payment_currency_id": self.eur_currency.id,
                "payment_currency_amount": 50.0,
            }
        )
        self.assertEqual(payment.foreign_currency_id, self.eur_currency)
        self.assertTrue(payment.oca_core_foreign_mirrored)
        # The payment goes back to the order currency: the values this module
        # mirrored are cleared.
        payment.write(
            {
                "payment_currency_id": self.usd_currency.id,
                "payment_currency_amount": payment.amount,
            }
        )
        self.assertFalse(payment.foreign_currency_id)
        self.assertFalse(payment.amount_currency)
        self.assertFalse(payment.oca_core_foreign_mirrored)

    def test_core_native_foreign_fields_are_not_cleared(self):
        order = self._create_draft_order()
        payment = self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": 10.0,
                "payment_method_id": self.cash_payment_method.id,
                "foreign_currency_id": self.eur_currency.id,
                "amount_currency": 20.0,
            }
        )
        payment.write({"amount": 12.0, "payment_currency_amount": 12.0})
        self.assertEqual(payment.foreign_currency_id, self.eur_currency)
        self.assertAlmostEqual(payment.amount_currency, 20.0, places=2)
        self.assertFalse(payment.oca_core_foreign_mirrored)

    def _create_draft_order(self):
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        return self.env["pos.order"].create(
            {
                "session_id": session.id,
                "partner_id": self.partner1.id,
                "amount_total": 100.0,
                "amount_tax": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
            }
        )
