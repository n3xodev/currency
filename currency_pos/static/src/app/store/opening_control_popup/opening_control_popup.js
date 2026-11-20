import { OpeningControlPopup } from "@point_of_sale/app/components/popups/opening_control_popup/opening_control_popup";
import { patch } from "@web/core/utils/patch";
import { formatFloat } from "@web/core/utils/numbers";
import { MoneyDetailsPopup } from "@point_of_sale/app/components/popups/money_details_popup/money_details_popup";
import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError } from "@web/core/network/rpc";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { buildOpeningCashByMethod } from "@currency_pos/app/utils/opening_cash_utils";
import { getPaymentMethodCurrency } from "@currency_pos/app/utils/payment_currency_utils";

patch(OpeningControlPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.moneyDetailsByMethod = {};
        const openings = this.pos.session._oca_cash_box_openings || {};
        this.state.openingCashByMethod = buildOpeningCashByMethod({
            cashPaymentMethods: this.getCashPaymentMethods(),
            openings,
            primaryPaymentMethod: this.getPrimaryCashPaymentMethod(),
            cashRegisterBalanceStart: this.pos.config._last_opening_balance || 0,
            getCurrency: (paymentMethod) => this._getCashMethodCurrency(paymentMethod),
            companyCurrency: this.pos.currency,
            formatCurrency: (amount, withSymbol) => this._formatOpeningAmount(amount, withSymbol),
            formatFloat,
        });
    },

    getCashPaymentMethods() {
        return this.pos.config.payment_method_ids.filter((pm) => pm.type === "cash");
    },

    _formatOpeningAmount(amount, withSymbol = true) {
        return this.pos.formatCurrency(amount, this.pos.config.currency_id.id, {
            noSymbol: !withSymbol,
        });
    },

    _parseOpeningAmount(raw) {
        try {
            return this.pos.parseCurrency(raw);
        } catch {
            return NaN;
        }
    },

    getPrimaryCashPaymentMethod() {
        return this.getCashPaymentMethods()[0] || null;
    },

    _getCashMethodCurrency(paymentMethod) {
        return getPaymentMethodCurrency(paymentMethod, this.pos.models, this.pos.currency);
    },

    formatOpeningCashLabel(paymentMethod) {
        return paymentMethod.name;
    },

    getCurrencySymbol(paymentMethod) {
        const currency = this._getCashMethodCurrency(paymentMethod);
        return currency?.symbol || currency?.name || "";
    },

    async confirm() {
        const cashboxValues = {};
        for (const paymentMethod of this.getCashPaymentMethods()) {
            const raw = this.state.openingCashByMethod[paymentMethod.id];
            const amount = this.pos.isValidFloat(raw) ? this._parseOpeningAmount(raw) : NaN;
            if (Number.isNaN(amount)) {
                return;
            }
            cashboxValues[paymentMethod.id] = amount;
        }
        // queue only when known offline, so the reconnect loop is sure to replay it
        const queue = this.pos.data.network.offline;
        try {
            await this.pos.data.callRelated(
                "pos.session",
                "oca_set_opening_control",
                [this.pos.session.id, cashboxValues, this.state.notes],
                {},
                queue
            );
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                this.dialog.add(AlertDialog, {
                    title: _t("Connection Lost"),
                    body: _t("The register cannot be opened while offline. Please try again."),
                });
                return;
            }
            return this.pos.reloadIfSessionDeleted(error);
        }
        this.pos.session.state = "opened";
        this.props.close();
    },

    async openDetailsPopup(paymentMethod) {
        const method = paymentMethod || this.getPrimaryCashPaymentMethod();
        if (!method) {
            return;
        }
        const action = _t("Cash control - opening");
        await this.pos.openCashbox(action);
        const currency = this._getCashMethodCurrency(method);
        this.dialog.add(MoneyDetailsPopup, {
            moneyDetails: this.moneyDetailsByMethod[method.id] || null,
            action: action,
            getPayload: (payload) => {
                if (payload) {
                    const { total, moneyDetails, moneyDetailsNotes } = payload;
                    const isForeign = currency && currency.id !== this.pos.currency.id;
                    this.state.openingCashByMethod[method.id] = isForeign
                        ? formatFloat(total, {
                              digits: [true, currency.decimal_places ?? 2],
                          })
                        : this._formatOpeningAmount(total, false);
                    if (method === this.getPrimaryCashPaymentMethod()) {
                        this.state.openingCash = this.state.openingCashByMethod[method.id];
                    }
                    if (moneyDetailsNotes) {
                        this.state.notes = moneyDetailsNotes;
                    }
                    this.moneyDetailsByMethod[method.id] = moneyDetails;
                }
            },
            context: "Opening",
        });
    },

    getCurrencyPosition(paymentMethod) {
        const currency = this._getCashMethodCurrency(paymentMethod);
        return currency && currency.id !== this.pos.currency.id ? "after" : this.pos.currency.position;
    },

    handleMethodInputChange(paymentMethod) {
        if (!this.pos.isValidFloat(this.state.openingCashByMethod[paymentMethod.id])) {
            return;
        }
        this.state.notes = "";
    },

    canConfirmOpening() {
        if (!this.cashMethodCount) {
            return true;
        }
        return this.getCashPaymentMethods().every((paymentMethod) =>
            this.pos.isValidFloat(this.state.openingCashByMethod[paymentMethod.id])
        );
    },
});
