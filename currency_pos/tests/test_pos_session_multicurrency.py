from odoo import fields
from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon


@tagged("post_install", "-at_install", "currency_pos")
class TestPosSessionMulticurrency(TestPosPaymentCurrencyCommon):
    def test_session_payment_amount_in_method_currency(self):
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "partner_id": self.partner1.id,
                "amount_total": 100.0,
                "amount_tax": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
            }
        )
        payment = self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": 0.0,
                "payment_method_id": self.eur_bank_payment_method.id,
                "payment_currency_id": self.eur_currency.id,
                "payment_currency_amount": 50.0,
            }
        )
        amount_currency, currency = session._oca_amount_in_payment_method_currency(
            payment,
            self.eur_bank_payment_method,
        )
        self.assertEqual(currency, self.eur_currency)
        self.assertEqual(amount_currency, 50.0)
        self.assertGreater(payment.amount, 0.0)

    def test_nested_payment_create_persists_foreign_amount(self):
        order = self._create_paid_order()
        payment = self.env["pos.payment"].create(
            {
                "amount": 0.0,
                "payment_method_id": self.eur_bank_payment_method.id,
                "payment_currency_amount": 25.0,
                "payment_currency_id": self.eur_currency.id,
                "pos_order_id": order.id,
            }
        )
        self.assertEqual(payment.payment_currency_id, self.eur_currency)
        self.assertEqual(payment.payment_currency_amount, 25.0)
        self.assertGreater(payment.amount, 0.0)

    def test_closing_control_data_shows_foreign_currency(self):
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "partner_id": self.partner1.id,
                "amount_total": 100.0,
                "amount_tax": 0.0,
                "amount_paid": 100.0,
                "amount_return": 0.0,
                "state": "paid",
            }
        )
        self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": 0.0,
                "payment_method_id": self.eur_bank_payment_method.id,
                "payment_currency_id": self.eur_currency.id,
                "payment_currency_amount": 40.0,
            }
        )
        closing_data = session.get_closing_control_data()
        eur_method = next(
            item
            for item in closing_data["non_cash_payment_methods"]
            if item["id"] == self.eur_bank_payment_method.id
        )
        self.assertTrue(eur_method["has_foreign_currency"])
        self.assertEqual(eur_method["amount_payment_currency"], 40.0)

    def test_closing_expected_matches_payment_currency_amount(self):
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "partner_id": self.partner1.id,
                "amount_total": 100.0,
                "amount_tax": 0.0,
                "amount_paid": 100.0,
                "amount_return": 0.0,
                "state": "paid",
            }
        )
        payment = self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": 0.0,
                "payment_method_id": self.eur_bank_payment_method.id,
                "payment_currency_id": self.eur_currency.id,
                "payment_currency_amount": 50.0,
            }
        )
        self.assertGreater(payment.amount, 0.0)
        closing_data = session.get_closing_control_data()
        eur_method = next(
            item
            for item in closing_data["non_cash_payment_methods"]
            if item["id"] == self.eur_bank_payment_method.id
        )
        self.assertEqual(eur_method["amount_payment_currency"], 50.0)
        self.assertAlmostEqual(eur_method["amount"], payment.amount, places=2)

    def test_cash_change_only_in_order_currency(self):
        order = self._create_paid_order()
        payment = self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": -5.0,
                "payment_method_id": self.cash_payment_method.id,
                "is_change": True,
                "payment_currency_amount": -5.0,
                "payment_currency_id": self.usd_currency.id,
            }
        )
        self.assertEqual(payment.currency_id, self.usd_currency)
        self.assertEqual(payment.payment_currency_id, self.usd_currency)

    def test_usd_overpay_change_in_foreign_currency(self):
        """Pay more in USD, then register change as a negative foreign cash payment."""
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "partner_id": self.partner1.id,
                "amount_total": 80.0,
                "amount_tax": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
            }
        )
        self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": 100.0,
                "payment_method_id": self.cash_payment_method.id,
                "payment_currency_amount": 100.0,
                "payment_currency_id": self.usd_currency.id,
            }
        )
        # Remaining in order currency: -20 USD. Change in EUR (rate 2) => -40 EUR.
        change_foreign_amount = self.env["pos.payment"]._oca_convert_amount(
            -20.0,
            self.usd_currency,
            self.eur_currency,
            self.env.company,
            fields.Date.today(),
        )
        self.assertAlmostEqual(change_foreign_amount, -40.0, places=2)
        change_payment = self.env["pos.payment"].create(
            {
                "pos_order_id": order.id,
                "amount": 0.0,
                "payment_method_id": self.eur_cash_payment_method.id,
                "payment_currency_id": self.eur_currency.id,
                "payment_currency_amount": change_foreign_amount,
                "is_change": True,
            }
        )
        self.assertEqual(change_payment.payment_currency_id, self.eur_currency)
        self.assertAlmostEqual(change_payment.payment_currency_amount, -40.0, places=2)
        self.assertLess(change_payment.amount, 0.0)
        self.assertAlmostEqual(change_payment.amount, -20.0, places=2)
        paid = sum(order.payment_ids.mapped("amount"))
        self.assertAlmostEqual(paid, 80.0, places=2)

    def test_opening_creates_cash_boxes_per_cash_method(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(10)
        self.assertEqual(len(session.cash_box_ids), 2)
        primary_box = session.cash_box_ids.filtered(
            lambda box: box.payment_method_id == self.cash_payment_method
        )
        eur_box = session.cash_box_ids.filtered(
            lambda box: box.payment_method_id == self.eur_cash_payment_method
        )
        self.assertEqual(len(primary_box), 1)
        self.assertEqual(len(eur_box), 1)
        self.assertAlmostEqual(primary_box.balance_start, 10.0, places=2)
        self.assertEqual(eur_box.currency_id, self.eur_currency)

    def test_closing_expected_includes_opening_amounts(self):
        self.config = self.multi_currency_config
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        session.oca_set_opening_control(
            {
                self.cash_payment_method.id: 5.0,
                self.eur_cash_payment_method.id: 20.0,
            },
            "multi opening",
        )
        closing_data = session.get_closing_control_data()
        primary = next(
            item
            for item in closing_data["default_cash_details"]["cash_details"]
            if item["id"] == self.cash_payment_method.id
        )
        eur_cash = next(
            item
            for item in closing_data["default_cash_details"]["cash_details"]
            if item["id"] == self.eur_cash_payment_method.id
        )
        self.assertAlmostEqual(primary["opening"], 5.0, places=2)
        self.assertAlmostEqual(primary["amount"], 5.0, places=2)
        self.assertAlmostEqual(eur_cash["opening"], 20.0, places=2)
        self.assertAlmostEqual(eur_cash["amount"], 20.0, places=2)
        self.assertAlmostEqual(eur_cash["amount"] - 0.0, 20.0, places=2)

    def test_next_session_suggests_previous_cash_box_balances(self):
        self.config = self.multi_currency_config
        self.multi_currency_config.open_ui()
        first_session = self.multi_currency_config.current_session_id
        first_session.oca_set_opening_control(
            {
                self.cash_payment_method.id: 5.0,
                self.eur_cash_payment_method.id: 20.0,
            },
            False,
        )
        first_session.close_session_from_ui(
            {
                self.cash_payment_method.id: 5.0,
                self.eur_cash_payment_method.id: 20.0,
            }
        )
        self.assertEqual(first_session.state, "closed")

        self.multi_currency_config.open_ui()
        second_session = self.multi_currency_config.current_session_id
        openings = second_session._oca_get_cash_box_opening_map()
        self.assertAlmostEqual(openings[self.cash_payment_method.id], 5.0, places=2)
        self.assertAlmostEqual(openings[self.eur_cash_payment_method.id], 20.0, places=2)
        loaded = self.env["pos.session"]._load_pos_data_read(
            second_session, second_session.config_id
        )
        self.assertIn("_oca_cash_box_openings", loaded[0])
        self.assertNotIn("_rt_cash_box_openings", loaded[0])
        self.assertNotIn("rt_cash_box_openings", loaded[0])
        self.assertAlmostEqual(
            loaded[0]["_oca_cash_box_openings"][self.cash_payment_method.id],
            5.0,
            places=2,
        )
        self.assertAlmostEqual(
            loaded[0]["_oca_cash_box_openings"][self.eur_cash_payment_method.id],
            20.0,
            places=2,
        )

    def test_cash_in_out_on_foreign_cash_method(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        session.try_cash_in_out(
            "in",
            20.0,
            "Float EUR",
            False,
            {
                "translatedType": "in",
                "formattedAmount": "20.00",
                "payment_method_id": self.eur_cash_payment_method.id,
            },
        )
        move = session._oca_statement_lines(self.eur_cash_journal)
        self.assertEqual(len(move), 1)
        self.assertAlmostEqual(move.amount, 20.0, places=2)

    def test_closing_control_lists_all_cash_methods(self):
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        order_data = self.create_ui_order_data(
            [(self.product_mc, 1)],
            payments=[(self.eur_cash_payment_method, 100.0)],
        )
        self.env["pos.order"].sync_from_ui([order_data])
        payment = session.order_ids.payment_ids.filtered(
            lambda pay: pay.payment_method_id == self.eur_cash_payment_method
        )
        self.assertEqual(payment.payment_currency_id, self.eur_currency)
        closing_data = session.get_closing_control_data()
        self.assertEqual(len(closing_data["default_cash_details"]["cash_details"]), 2)
        eur_cash = next(
            item
            for item in closing_data["default_cash_details"]["cash_details"]
            if item["id"] == self.eur_cash_payment_method.id
        )
        self.assertTrue(eur_cash["has_foreign_currency"])
        self.assertAlmostEqual(
            eur_cash["amount_payment_currency"],
            payment.payment_currency_amount,
            places=2,
        )
        cash_ids = {item["id"] for item in closing_data["default_cash_details"]["cash_details"]}
        non_cash_ids = {item["id"] for item in closing_data["non_cash_payment_methods"]}
        self.assertIn(self.eur_cash_payment_method.id, cash_ids)
        self.assertNotIn(self.eur_cash_payment_method.id, non_cash_ids)

    def _create_paid_order(self):
        self.multi_currency_config.open_ui()
        session = self.multi_currency_config.current_session_id
        return self.env["pos.order"].create(
            {
                "session_id": session.id,
                "partner_id": self.partner1.id,
                "amount_total": 100.0,
                "amount_tax": 0.0,
                "amount_paid": 100.0,
                "amount_return": 0.0,
                "state": "paid",
            }
        )


@tagged("post_install", "-at_install", "currency_pos")
class TestPosSessionLoadDataRead(TestPosPaymentCurrencyCommon):
    def test_device_sync_of_session_does_not_raise(self):
        # pos_hr writes `employee_id` on the session at cashier login, which
        # makes core dispatch a device sync of {"pos.session": [id]}. That
        # calls `_load_pos_data_read` on the EMPTY model with the real session
        # in `records`.
        config = self.multi_currency_config
        config.open_ui()
        session = config.current_session_id
        config.notify_synchronisation(session.id, "test-device", {"pos.session": [session.id]})

    def test_load_pos_data_read_returns_cash_box_openings_per_row(self):
        config = self.multi_currency_config
        config.open_ui()
        session = config.current_session_id
        rows = self.env["pos.session"]._load_pos_data_read(session, config)
        self.assertEqual(len(rows), 1)
        openings = rows[0]["_oca_cash_box_openings"]
        cash_method_ids = set(config.payment_method_ids.filtered(lambda pm: pm.type == "cash").ids)
        self.assertTrue(cash_method_ids)
        self.assertEqual(set(openings), cash_method_ids)
