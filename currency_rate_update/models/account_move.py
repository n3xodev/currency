# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    def get_currency_rate(self, company_id, to_currency_id, requested_date):
        """Rate for the date picker widget, without the extra day of core.

        Core (account/models/account_move.py, ``get_currency_rate``) adds one day
        to compensate for the strict ``<`` of ``res.currency._get_rates``. Since
        this module restores the Odoo 19 same-day semantics in ``_get_rates``,
        keeping that shift would apply it twice and return the rate of D+1.
        """
        company = self.env["res.company"].browse(company_id)
        to_currency = self.env["res.currency"].browse(to_currency_id)
        return self.env["res.currency"]._get_conversion_rate(
            from_currency=company.currency_id,
            to_currency=to_currency,
            company=company,
            date=fields.Date.to_date(requested_date),
        )
