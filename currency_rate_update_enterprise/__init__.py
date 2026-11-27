# Copyright 2026 n3xodev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from . import models


def post_init_hook(env):
    companies = env["res.company"].sudo().with_context(active_test=False).search([
        "|",
        ("currency_interval_unit", "!=", "manually"),
        ("currency_next_execution_date", "!=", False),
    ])
    if companies:
        companies.write({
            "currency_interval_unit": "manually",
            "currency_next_execution_date": False,
        })
