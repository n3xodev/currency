import { CashMovePopup } from "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup";
import { patch } from "@web/core/utils/patch";
import { getPaymentMethodCurrency } from "@currency_pos/app/utils/payment_currency_utils";

/**
 * Cash in/out on a given cash box (cash payment method). Core 20 books the move
 * on the only cash method of the session; the selected method travels as the
 * `payment_method_id` keyword of `pos.session.try_cash_in_out`, and the receipt
 * and notifications are core's own `confirm()`.
 */
patch(CashMovePopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.paymentMethodId = this.getCashPaymentMethods()[0]?.id || false;
    },

    getCashPaymentMethods() {
        return this.pos.config.payment_method_ids.filter((pm) => pm.type === "cash");
    },

    getSelectedCashPaymentMethod() {
        const cashMethods = this.getCashPaymentMethods();
        return (
            cashMethods.find((pm) => pm.id === this.state.paymentMethodId) ||
            cashMethods[0] ||
            null
        );
    },

    get selectedCashCurrency() {
        return getPaymentMethodCurrency(
            this.getSelectedCashPaymentMethod(),
            this.pos.models,
            this.pos.currency
        );
    },

    get showCashMethodSelector() {
        return this.getCashPaymentMethods().length > 1;
    },

    _getCashInOutExtraParams() {
        const result = super._getCashInOutExtraParams(...arguments);
        const paymentMethod = this.getSelectedCashPaymentMethod();
        if (paymentMethod) {
            result.payment_method_id = paymentMethod.id;
        }
        return result;
    },
});
