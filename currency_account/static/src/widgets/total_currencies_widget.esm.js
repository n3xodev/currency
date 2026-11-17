/** @odoo-module **/

import { Component, useProps } from "@odoo/owl";
import { onWillRender } from "@web/owl2/utils";
import {formatMonetary} from "@web/views/fields/formatters";
import {registry} from "@web/core/registry";
import {standardFieldProps} from "@web/views/fields/standard_field_props";

export class TotalCurrenciesWidget extends Component {
    props = useProps({...standardFieldProps});
    static template = "currency_account.TotalCurrenciesWidget";

    setup() {
        super.setup();
        this.totals = [];
        this.hasResidual = false;
        this.formatData(this.props);
        onWillRender(() => this.formatData(this.props));
    }

    formatData(props) {
        const raw = props.record.data[this.props.name];
        if (!raw) {
            this.totals = [];
            this.hasResidual = false;
            return;
        }
        const totals = typeof raw === "string" ? JSON.parse(raw) : raw;
        if (!totals) {
            this.totals = [];
            this.hasResidual = false;
            return;
        }
        this.totals = Object.values(totals);
        this.hasResidual = this.totals.length > 0 && "residual" in this.totals[0];
    }

    formatAmount(total, key) {
        return formatMonetary(total[key], {currencyId: total.currency_id});
    }
}

registry
    .category("fields")
    .add("total_currencies_widget", {component: TotalCurrenciesWidget});
