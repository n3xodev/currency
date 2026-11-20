import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";
import { formatFloat } from "@web/core/utils/numbers";
import {
    convertCurrency,
    getCurrencyRecord,
    getPaymentMethodCurrency,
} from "../../utils/payment_currency_utils";
import { MoneyDetailsPopup } from "@point_of_sale/app/components/popups/money_details_popup/money_details_popup";
import { _t } from "@web/core/l10n/translation";

patch(ClosePosPopup.prototype, {
    setup() {
        this.moneyDetailsByMethod = {};
        super.setup();
    },

    /**
     * Cash boxes of the session. Odoo 20 declares the popup props with
     * `useProps`, so a `cash_details` prop of its own would not be readable:
     * the server nests the list in `default_cash_details.cash_details`.
     */
    getCashDetailsList() {
        const cashDetails = this.props.default_cash_details?.cash_details;
        if (cashDetails?.length) {
            return cashDetails;
        }
        if (this.props.default_cash_details?.id) {
            return [this.props.default_cash_details];
        }
        return [];
    },

    _parseCounted(counted) {
        if (!this.pos.isValidFloat(counted)) {
            return NaN;
        }
        try {
            return this.pos.parseCurrency(counted);
        } catch {
            return NaN;
        }
    },

    parseValidCounted(counted) {
        const parsed = this._parseCounted(counted);
        return Number.isNaN(parsed) ? 0 : parsed;
    },

    /** Counted amount as the input shows it: in the currency of the method. */
    _formatCountedInput(amount, paymentMethodData) {
        if (paymentMethodData?.has_foreign_currency) {
            const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
            return formatFloat(amount, {
                digits: [true, paymentCurrency?.decimal_places ?? this.pos.currency.decimal_places],
            });
        }
        return this.pos.formatCurrency(amount || 0, this.pos.config.currency_id.id, {
            noSymbol: true,
        });
    },

    getCurrencyPosition(paymentMethodData) {
        return paymentMethodData?.has_foreign_currency ? "after" : this.pos.currency.position;
    },

    handleCashBoxCountBlur(cashDetails) {
        this.handlePaymentCountBlur(cashDetails.id);
        this.setManualCashInput(this.state.payments[cashDetails.id].counted, cashDetails.id);
    },

    handlePaymentCountBlur(paymentId) {
        const paymentMethodData = this._getClosingPaymentMethodData(paymentId);
        const parsed = this._parseCounted(this.state.payments[paymentId].counted);
        if (!Number.isNaN(parsed)) {
            this.state.payments[paymentId].counted = this._formatCountedInput(
                parsed,
                paymentMethodData
            );
        }
    },

    _getClosingPaymentMethodData(paymentId) {
        const normalizedId = Number(paymentId);
        const cashDetails = this.getCashDetailsList().find((pm) => pm.id === normalizedId);
        if (cashDetails) {
            return cashDetails;
        }
        if (this.props.default_cash_details?.id === normalizedId) {
            return this.props.default_cash_details;
        }
        return this.props.non_cash_payment_methods.find((pm) => pm.id === normalizedId);
    },

    _getPaymentCurrencyRecord(paymentMethodData) {
        if (!paymentMethodData) {
            return null;
        }
        const fromDetails = getCurrencyRecord(
            this.pos.models,
            paymentMethodData.payment_currency_id
        );
        if (fromDetails) {
            return fromDetails;
        }
        const paymentMethod = this.pos.models["pos.payment.method"].get(paymentMethodData.id);
        return getPaymentMethodCurrency(paymentMethod, this.pos.models, null);
    },

    getCurrencySymbol(paymentMethodData) {
        const currency =
            this._getPaymentCurrencyRecord(paymentMethodData) || this.pos.currency;
        return currency?.symbol || currency?.name || "";
    },

    _parseClosingCountedAmount(paymentId) {
        return this._parseCounted(this.state.payments[paymentId]?.counted);
    },

    getExpectedClosingCount(paymentMethodData) {
        if (!paymentMethodData) {
            return 0;
        }
        // Cash boxes already store full expected in `amount` (opening + payments + moves).
        if (paymentMethodData.type === "cash" || Array.isArray(paymentMethodData.moves)) {
            return paymentMethodData.amount ?? 0;
        }
        if (!paymentMethodData.has_foreign_currency) {
            return paymentMethodData.amount ?? 0;
        }
        if (paymentMethodData.amount_payment_currency != null) {
            return paymentMethodData.amount_payment_currency;
        }
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
        if (!paymentCurrency) {
            return paymentMethodData.amount ?? 0;
        }
        return convertCurrency(
            paymentMethodData.amount,
            this.pos.currency,
            paymentCurrency,
            this.pos.models
        );
    },

    getForeignCountDifference(paymentMethodData, paymentId) {
        const counted = this._parseClosingCountedAmount(paymentId);
        if (Number.isNaN(counted)) {
            return NaN;
        }
        return counted - this.getExpectedClosingCount(paymentMethodData);
    },

    formatClosingCountInput(paymentMethodData) {
        if (!paymentMethodData) {
            return "0";
        }
        if (paymentMethodData.has_foreign_currency) {
            return this._formatCountedInput(
                this.getExpectedClosingCount(paymentMethodData),
                paymentMethodData
            );
        }
        return this._formatCountedInput(paymentMethodData.amount, paymentMethodData);
    },

    formatClosingPaymentAmount(paymentMethodData) {
        if (!paymentMethodData) {
            return "";
        }
        if (paymentMethodData.type === "cash" || paymentMethodData.moves) {
            return this.formatClosingCashExpected(paymentMethodData);
        }
        const orderAmount = this.pos.formatCurrency(paymentMethodData.amount);
        if (!paymentMethodData.has_foreign_currency) {
            return orderAmount;
        }
        const symbol =
            paymentMethodData.payment_currency_symbol ||
            paymentMethodData.payment_currency_name ||
            "";
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
        const decimalPlaces =
            paymentCurrency?.decimal_places ?? this.pos.currency.decimal_places;
        const formattedForeign = formatFloat(this.getExpectedClosingCount(paymentMethodData), {
            digits: [true, decimalPlaces],
        });
        const foreignAmount = `${formattedForeign} ${symbol}`.trim();
        return `${foreignAmount} (${orderAmount})`;
    },

    formatClosingCashExpected(paymentMethodData) {
        if (!paymentMethodData?.has_foreign_currency) {
            return this.pos.formatCurrency(paymentMethodData.amount);
        }
        const symbol =
            paymentMethodData.payment_currency_symbol ||
            paymentMethodData.payment_currency_name ||
            "";
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
        const decimalPlaces =
            paymentCurrency?.decimal_places ?? this.pos.currency.decimal_places;
        const formattedForeign = formatFloat(this.getExpectedClosingCount(paymentMethodData), {
            digits: [true, decimalPlaces],
        });
        return `${formattedForeign} ${symbol}`.trim();
    },

    formatClosingCashOpening(paymentMethodData) {
        if (!paymentMethodData?.has_foreign_currency) {
            return this.pos.formatCurrency(paymentMethodData.opening);
        }
        const symbol =
            paymentMethodData.payment_currency_symbol ||
            paymentMethodData.payment_currency_name ||
            "";
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
        const decimalPlaces =
            paymentCurrency?.decimal_places ?? this.pos.currency.decimal_places;
        const formatted = formatFloat(paymentMethodData.opening || 0, {
            digits: [true, decimalPlaces],
        });
        return `${formatted} ${symbol}`.trim();
    },

    formatClosingPaymentSubAmount(paymentMethodData) {
        if (!paymentMethodData?.has_foreign_currency) {
            return this.pos.formatCurrency(
                Math.abs(paymentMethodData?.payment_amount || 0)
            );
        }
        const symbol =
            paymentMethodData.payment_currency_symbol ||
            paymentMethodData.payment_currency_name ||
            "";
        const orderAmount = this.pos.formatCurrency(
            Math.abs(paymentMethodData.payment_amount || 0)
        );
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
        const decimalPlaces =
            paymentCurrency?.decimal_places ?? this.pos.currency.decimal_places;
        const formattedForeign = formatFloat(
            Math.abs(paymentMethodData.payment_amount_payment_currency || 0),
            { digits: [true, decimalPlaces] }
        );
        const foreignAmount = `${formattedForeign} ${symbol}`.trim();
        return `${foreignAmount} (${orderAmount})`;
    },

    formatClosingCountedDisplay(paymentMethodData, counted) {
        if (!paymentMethodData?.has_foreign_currency) {
            return this.pos.formatCurrency(counted);
        }
        const symbol =
            paymentMethodData.payment_currency_symbol ||
            paymentMethodData.payment_currency_name ||
            "";
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
        const decimalPlaces =
            paymentCurrency?.decimal_places ?? this.pos.currency.decimal_places;
        const formattedCounted = formatFloat(counted, { digits: [true, decimalPlaces] });
        return `${formattedCounted} ${symbol}`.trim();
    },

    formatClosingDifferenceDisplay(paymentMethodData, paymentId) {
        const paymentMethod = paymentMethodData || this._getClosingPaymentMethodData(paymentId);
        const normalizedId = Number(paymentId);
        if (!this.state.payments[normalizedId]) {
            // Methods that are not counted (customer account, ...) have no difference.
            return this.pos.formatCurrency(0);
        }
        if (!paymentMethod?.has_foreign_currency) {
            return this.pos.formatCurrency(this.getDifference(normalizedId));
        }
        const diffForeign = this.getForeignCountDifference(paymentMethod, normalizedId);
        const symbol =
            paymentMethod.payment_currency_symbol ||
            paymentMethod.payment_currency_name ||
            "";
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethod);
        const decimalPlaces =
            paymentCurrency?.decimal_places ?? this.pos.currency.decimal_places;
        const formattedDiff = formatFloat(diffForeign, { digits: [true, decimalPlaces] });
        const orderDiff = this.pos.formatCurrency(
            this._convertForeignCountDifferenceToOrderCurrency(diffForeign, paymentMethod)
        );
        return `${formattedDiff} ${symbol} (${orderDiff})`.trim();
    },

    _convertForeignCountDifferenceToOrderCurrency(diffForeign, paymentMethodData) {
        const paymentCurrency = this._getPaymentCurrencyRecord(paymentMethodData);
        if (!paymentCurrency) {
            return diffForeign;
        }
        return convertCurrency(
            diffForeign,
            paymentCurrency,
            this.pos.currency,
            this.pos.models
        );
    },

    getCashMoveData(cashDetails) {
        const details = cashDetails || this.props.default_cash_details;
        const { total, moves } = (details?.moves || []).reduce(
            (acc, move, i) => {
                acc.total += move.amount;
                acc.moves.push({
                    id: i,
                    name: move.name,
                    amount: move.amount,
                });
                return acc;
            },
            { total: 0, moves: [] }
        );
        return { total, moves };
    },

    get cashMoveData() {
        return this.getCashMoveData(this.props.default_cash_details);
    },

    getInitialState() {
        const initialState = { notes: "", payments: {} };
        if (this.pos.config.cash_control) {
            for (const cashDetails of this.getCashDetailsList()) {
                initialState.payments[cashDetails.id] = {
                    counted: this.formatClosingCountInput(cashDetails),
                };
            }
        }
        this.props.non_cash_payment_methods.forEach((pm) => {
            if (pm.type === "bank") {
                initialState.payments[pm.id] = {
                    counted: this.formatClosingCountInput(pm),
                };
            }
        });
        return initialState;
    },

    autoFillCashCount(cashDetails) {
        const details = cashDetails || this.getCashDetailsList()[0];
        if (!details) {
            return;
        }
        this.state.payments[details.id].counted = this.formatClosingCountInput(details);
        this.setManualCashInput(this.state.payments[details.id].counted, details.id);
    },

    setManualCashInput(amount, paymentMethodId) {
        if (this.pos.isValidFloat(amount)) {
            const methodId = paymentMethodId || this.props.default_cash_details?.id;
            if (methodId && this.moneyDetailsByMethod[methodId]) {
                this.state.notes = "";
                this.moneyDetailsByMethod[methodId] = null;
            } else if (this.moneyDetails) {
                this.state.notes = "";
                this.moneyDetails = null;
            }
        }
    },

    async openDetailsPopup(cashDetails) {
        const details = cashDetails || this.getCashDetailsList()[0];
        if (!details) {
            return;
        }
        const action = _t("Cash control - closing");
        await this.pos.openCashbox(action);
        this.dialog.add(MoneyDetailsPopup, {
            moneyDetails: this.moneyDetailsByMethod[details.id] || null,
            action: action,
            getPayload: (payload) => {
                const { total, moneyDetailsNotes, moneyDetails } = payload;
                this.state.payments[details.id].counted = this._formatCountedInput(
                    total,
                    details
                );
                if (moneyDetailsNotes) {
                    this.state.notes = moneyDetailsNotes;
                }
                this.moneyDetailsByMethod[details.id] = moneyDetails;
            },
            context: "Closing",
        });
    },

    getDifference(paymentId) {
        const normalizedId = Number(paymentId);
        const paymentMethodData = this._getClosingPaymentMethodData(normalizedId);
        if (Number.isNaN(this._parseClosingCountedAmount(normalizedId))) {
            return NaN;
        }
        if (paymentMethodData?.has_foreign_currency) {
            const diffForeign = this.getForeignCountDifference(
                paymentMethodData,
                normalizedId
            );
            return this._convertForeignCountDifferenceToOrderCurrency(
                diffForeign,
                paymentMethodData
            );
        }
        const counted = this._parseClosingCountedAmount(normalizedId);
        const expectedAmount = this.getExpectedClosingCount(paymentMethodData);
        return counted - expectedAmount;
    },
});
