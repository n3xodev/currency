# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import api, fields, models


class ResCurrency(models.Model):
    _inherit = "res.currency"

    @api.model
    def _get_rates(self, company, date):
        """Apply the rate dated D on day D, as Odoo 19 did.

        Odoo 19 selected the last rate with ``name <= date``. Odoo 20 selects
        ``name < date`` (odoo/addons/base/models/res_currency.py, ``_get_rates``),
        so a rate dated D only applies from D+1. Venezuelan users load the BCV
        rate of day D and expect it to be used for documents of day D, so the
        Odoo 19 semantics are restored on purpose by asking core for D+1.

        ``date`` may be a ``date``, a ``datetime`` or a string (the context
        ``date`` is ``str(date)``). The core cache key is (root company, date),
        which stays consistent because every caller goes through this method.

        Known limitation: three statistics-only SQL paths do not use
        ``_get_rates`` and keep the previous day's rate: account
        ``total_invoiced`` (account/models/partner.py), sale ``utm.campaign``
        (sale/models/utm_campaign.py) and ``mailing.mailing``
        (mass_mailing_sale/models/mailing_mailing.py). Accepted and documented.
        """
        date = fields.Date.to_date(date)
        if date:
            date += timedelta(days=1)
        return super()._get_rates(company, date)
