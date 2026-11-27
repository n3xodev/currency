# Copyright 2026 n3xodev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        sanitized = []
        for vals in vals_list:
            if (
                vals.get("currency_interval_unit") not in (None, False, "manually")
                or vals.get("currency_next_execution_date")
            ):
                vals = dict(vals)
                vals["currency_interval_unit"] = "manually"
                vals["currency_next_execution_date"] = False
            sanitized.append(vals)
        return super().create(sanitized)

    def write(self, vals):
        if (
            vals.get("currency_interval_unit") not in (None, False, "manually")
            or vals.get("currency_next_execution_date")
        ):
            vals = dict(vals)
            vals["currency_interval_unit"] = "manually"
            vals["currency_next_execution_date"] = False
        return super().write(vals)

    @api.model
    def run_update_currency(self):
        _logger.debug(
            "currency_rate_update_enterprise: skipping currency_rate_live cron "
            "because OCA currency_rate_update manages exchange rates."
        )
        return False
