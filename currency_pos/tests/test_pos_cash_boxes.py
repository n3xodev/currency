from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon


@tagged("post_install", "-at_install", "currency_pos")
class TestPosCashBoxes(TestPosPaymentCurrencyCommon):
    def test_config_keeps_one_cash_box_per_cash_method(self):
        config = self.multi_currency_config
        cash_methods = config.payment_method_ids.filtered(lambda pm: pm.type == "cash")
        self.assertEqual(len(cash_methods), 2)
        # Core 20 raises with more than one cash method; the first one stays
        # the primary box tracked by the session bank statement.
        self.assertEqual(config._get_cash_payment_method(), cash_methods[:1])

    def test_cash_method_stays_in_a_single_shop(self):
        other_config = self.env["pos.config"].create(
            {
                "name": "POS Other Shop",
                "journal_id": self.company_data["default_journal_sale"].id,
            }
        )
        with self.assertRaises(ValidationError):
            other_config.write({"payment_method_ids": [(4, self.eur_cash_payment_method.id)]})

    def test_closing_keeps_counted_amount_and_difference_per_box(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(10)
        eur_box = session._oca_get_cash_box(self.eur_cash_payment_method)
        eur_box.balance_start = 20.0
        session.try_cash_in_out(
            "in",
            5.0,
            "Float EUR",
            False,
            {"payment_method_id": self.eur_cash_payment_method.id},
        )
        session.close_session_from_ui(
            {
                self.cash_payment_method.id: 10.0,
                self.eur_cash_payment_method.id: 30.0,
            }
        )
        self.assertEqual(session.state, "closed")
        primary_box = session._oca_get_cash_box(self.cash_payment_method)
        self.assertAlmostEqual(primary_box.balance_end_real, 10.0, places=2)
        self.assertAlmostEqual(primary_box.closing_difference, 0.0, places=2)
        # 20 opening + 5 cash in = 25 expected, 30 counted.
        self.assertAlmostEqual(eur_box.balance_end_real, 30.0, places=2)
        self.assertAlmostEqual(eur_box.closing_difference, 5.0, places=2)

    def test_closing_control_data_lists_cash_moves_of_each_box(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        session.try_cash_in_out(
            "in",
            7.0,
            "Float EUR",
            False,
            {"payment_method_id": self.eur_cash_payment_method.id},
        )
        session.try_cash_in_out("in", 3.0, "Float USD", False)
        closing_data = session.get_closing_control_data()
        cash_details = {item["id"]: item for item in closing_data["default_cash_details"]["cash_details"]}
        eur_moves = cash_details[self.eur_cash_payment_method.id]["moves"]
        self.assertEqual([move["amount"] for move in eur_moves], [7.0])
        self.assertTrue(eur_moves[0]["id"])
        self.assertAlmostEqual(
            cash_details[self.eur_cash_payment_method.id]["amount"], 7.0, places=2
        )
        # Core books the cash in of the primary box on its bank statement.
        usd_moves = cash_details[self.cash_payment_method.id]["moves"]
        self.assertEqual([move["amount"] for move in usd_moves], [3.0])
        self.assertAlmostEqual(
            cash_details[self.cash_payment_method.id]["amount"], 3.0, places=2
        )

    def test_pos_data_loads_currencies_and_rates(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        data = session.load_data({"only_records": True})
        currency_ids = {currency["id"] for currency in data["res.currency"]}
        self.assertIn(self.eur_currency.id, currency_ids)
        rate_currency_ids = {
            rate["currency_id"] for rate in data["res.currency.rate"]
        }
        self.assertIn(self.eur_currency.id, rate_currency_ids)

    def _sync_order(self, payments, **order_args):
        order_data = self.create_ui_order_data(
            [(self.product_mc, 1)],
            payments=payments,
            pos_order_ui_args=order_args,
        )
        return self.env["pos.order"].sync_from_ui([order_data])

    def test_change_is_part_of_the_primary_box(self):
        """Pay 120 for a 100 order: core registers a -20 change payment and the
        drawer holds 100, not 120."""
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._sync_order([(self.cash_payment_method, 120.0)], amount_return=-20.0)
        change = session.order_ids.payment_ids.filtered("is_change")
        self.assertEqual(change.payment_method_id, self.cash_payment_method)
        self.assertAlmostEqual(change.amount, -20.0, places=2)
        closing_data = session.get_closing_control_data()
        primary = next(
            box
            for box in closing_data["default_cash_details"]["cash_details"]
            if box["id"] == self.cash_payment_method.id
        )
        self.assertAlmostEqual(primary["amount"], 100.0, places=2)
        self.assertAlmostEqual(primary["payment_amount"], 100.0, places=2)
        session.close_session_from_ui({str(self.cash_payment_method.id): 100.0})
        self.assertEqual(session.state, "closed")
        primary_box = session._oca_get_cash_box(self.cash_payment_method)
        self.assertAlmostEqual(primary_box.closing_difference, 0.0, places=2)
        # No cash difference line: the counted drawer matches core's balance.
        journal = self.cash_payment_method.journal_id
        difference_lines = session._oca_statement_lines(journal).filtered(
            lambda line: journal.profit_account_id | journal.loss_account_id
            in line.move_id.line_ids.account_id
        )
        self.assertFalse(difference_lines)

    def test_change_is_part_of_a_secondary_box(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._sync_order([(self.eur_cash_payment_method, 100.0)])
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
        closing_data = session.get_closing_control_data()
        eur_box = next(
            box
            for box in closing_data["default_cash_details"]["cash_details"]
            if box["id"] == self.eur_cash_payment_method.id
        )
        self.assertAlmostEqual(eur_box["amount"], 200.0, places=2)

    def test_accounting_without_closing_keeps_the_stored_counts(self):
        """Only the closing popup stores the counts, not other callers of the accounting."""
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        eur_box = session._oca_get_cash_box(self.eur_cash_payment_method)
        eur_box.balance_end_real = 123.0
        session._validate_session_accounting()
        self.assertAlmostEqual(eur_box.balance_end_real, 123.0, places=2)

    def test_opening_answers_with_the_reloaded_session(self):
        self.config = self.multi_currency_config
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        values = {self.cash_payment_method.id: 5.0, self.eur_cash_payment_method.id: 20.0}
        result = session.oca_set_opening_control(values, False)
        self.assertEqual(session.state, "opened")
        self.assertEqual([row["id"] for row in result["pos.session"]], session.ids)
        self.assertEqual(
            result["pos.session"][0]["_oca_cash_box_openings"][self.eur_cash_payment_method.id],
            20.0,
        )
        # Opening again (second device) gives the same answer without touching the boxes.
        again = session.oca_set_opening_control({self.eur_cash_payment_method.id: 99.0}, False)
        self.assertEqual([row["id"] for row in again["pos.session"]], session.ids)
        self.assertAlmostEqual(
            session._oca_get_cash_box(self.eur_cash_payment_method).balance_start, 20.0, places=2
        )
