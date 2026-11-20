from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PosConfig(models.Model):
    _inherit = "pos.config"

    allow_multi_currency_payment = fields.Boolean(
        string="Allow Payments in Other Currencies",
        default=False,
        help="Allow payment methods whose journal currency differs from the POS currency.",
    )

    def _get_cash_payment_method(self):
        """Primary cash method of the config.

        Odoo 20 raises when a config has more than one cash method; here every
        cash method is a cash box and the first one is the primary box, the one
        core keeps tracking with its bank statement (opening, cash in/out).
        """
        self.ensure_one()
        return self.payment_method_ids.filtered(lambda pm: pm.type == "cash")[:1]

    @api.constrains("payment_method_ids")
    def _check_payment_methods(self):
        """Core 20 allows a single cash method per config; cash boxes need several."""
        return

    @api.depends("payment_method_ids.account_bank_statement_id.balance_end")
    def _compute_current_cash_register_balance(self):
        for config in self:
            cash_method = config._get_cash_payment_method()
            config.current_cash_register_balance = (
                cash_method.journal_id.current_statement_balance if cash_method else 0
            )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if not fields_list:
            return fields_list
        if "allow_multi_currency_payment" not in fields_list:
            fields_list.append("allow_multi_currency_payment")
        return fields_list

    @api.constrains(
        "pricelist_id",
        "use_pricelist",
        "available_pricelist_ids",
        "journal_id",
        "payment_method_ids",
        "allow_multi_currency_payment",
    )
    def _check_currencies(self):
        # Replaces core's check on purpose (no super): like in 19, pricelists in
        # another currency than the POS must stay allowed (alternate-currency pricelists).
        for config in self:
            if (
                config.use_pricelist
                and config.pricelist_id
                and config.pricelist_id not in config.available_pricelist_ids
            ):
                raise ValidationError(
                    _("The default pricelist must be included in the available pricelists.")
                )

            if not config.allow_multi_currency_payment:
                for pm in config.payment_method_ids:
                    if (
                        pm.journal_id
                        and pm.journal_id.currency_id
                        and pm.journal_id.currency_id != config.currency_id
                    ):
                        raise ValidationError(
                            _(
                                "All payment methods must be in the same currency as the Sales "
                                "Journal or the company currency if that is not set."
                            )
                        )
