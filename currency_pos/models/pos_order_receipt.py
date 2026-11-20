from odoo import models


class PosOrderReceipt(models.AbstractModel):
    _inherit = "pos.order.receipt"

    def _order_receipt_generate_payment_data(self):
        """Show a foreign payment in its own currency, with the order amount next to it.

        Odoo 19 printed `200.00 EUR` followed by `(100.00 $)` for a payment made
        in a currency other than the one of the order; the receipt of Odoo 20 is
        built from these data by `point_of_sale.pos_order_receipt`.
        """
        payments = super()._order_receipt_generate_payment_data()
        payment_by_id = {payment.id: payment for payment in self.payment_ids}
        # Same rule as isForeignCurrencyPayment() of the POS client.
        multi_currency = self.config_id.allow_multi_currency_payment
        for data in payments:
            payment = payment_by_id.get(data["id"])
            if multi_currency and payment and payment.is_foreign_currency_payment:
                data["amount"] = self._order_receipt_format_currency(
                    payment.payment_currency_amount, payment.payment_currency_id
                )
                data["amount_order_currency"] = self._order_receipt_format_currency(
                    payment.amount
                )
            else:
                data["amount_order_currency"] = False
        return payments
