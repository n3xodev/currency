import json

from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon


@tagged("post_install", "-at_install", "currency_pos")
class TestPosClosingPopup(TestPosPaymentCurrencyCommon):
    def _pay_order(self, payments):
        order_data = self.create_ui_order_data([(self.product_mc, 1)], payments=payments)
        return self.env["pos.order"].sync_from_ui([order_data])

    def test_closing_popup_contract(self):
        """The popup reads the cash boxes nested in `default_cash_details` and
        sends {payment_method_id: counted} with string keys (JSON)."""
        self.config = self.multi_currency_config
        session = self.open_new_session(0)
        self._pay_order(
            [
                (self.cash_payment_method, 40.0),
                (self.eur_cash_payment_method, 20.0),
                (self.eur_bank_payment_method, 40.0),
            ]
        )
        closing_data = json.loads(json.dumps(session.get_closing_control_data(), default=str))
        # The popup declares its props with `useProps`: only the nested list is readable.
        self.assertNotIn("cash_details", closing_data)
        default_cash = closing_data["default_cash_details"]
        self.assertEqual(
            [box["id"] for box in default_cash["cash_details"]],
            [self.cash_payment_method.id, self.eur_cash_payment_method.id],
        )
        self.assertEqual(default_cash["id"], self.cash_payment_method.id)
        eur_cash = default_cash["cash_details"][1]
        eur_bank = next(
            pm
            for pm in closing_data["non_cash_payment_methods"]
            if pm["id"] == self.eur_bank_payment_method.id
        )
        # Foreign boxes are counted in the currency of the method (rate 2.0).
        self.assertAlmostEqual(eur_cash["amount"], 40.0, places=2)
        self.assertAlmostEqual(eur_bank["amount_payment_currency"], 80.0, places=2)
        payload = {
            str(self.cash_payment_method.id): 40.0,
            str(self.eur_cash_payment_method.id): eur_cash["amount"],
            str(self.eur_bank_payment_method.id): eur_bank["amount_payment_currency"],
        }
        response = session.close_session_from_ui(payload)
        self.assertEqual(response, {"status": True})
        self.assertEqual(session.state, "closed")
        self.assertFalse(session.correction_move_ids)
        eur_box = session._oca_get_cash_box(self.eur_cash_payment_method)
        self.assertAlmostEqual(eur_box.balance_end_real, 40.0, places=2)
        self.assertAlmostEqual(eur_box.closing_difference, 0.0, places=2)
