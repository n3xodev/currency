import { patch } from "@web/core/utils/patch";
import { GeneratePrinterData } from "@point_of_sale/app/utils/printer/generate_printer_data";

/**
 * JS copy of PosOrderReceipt._order_receipt_generate_payment_data of currency_pos.
 *
 * The receipt is also generated in the browser, from the order as it is before
 * the server answers: there the payment currency lives in the module's own
 * payment_currency_* fields, core's foreign_currency_id is not set yet.
 */
patch(GeneratePrinterData.prototype, {
    generatePaymentData() {
        const payments = super.generatePaymentData(...arguments);
        const lines = this.order.payment_ids;
        return payments.map((data, index) => {
            const line = lines[index];
            if (!line?.isForeignCurrencyPayment?.()) {
                return { ...data, amount_order_currency: false };
            }
            return {
                ...data,
                amount: this.formatCurrency(
                    line.getPaymentAmountCurrency(),
                    line.getPaymentCurrency()
                ),
                amount_order_currency: this.formatCurrency(line.getAmount()),
            };
        });
    },
});
