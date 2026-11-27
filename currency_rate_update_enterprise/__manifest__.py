# Copyright 2026 n3xodev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Currency Rate Update - Enterprise Bridge",
    "version": "20.0.1.0.0",
    "author": "n3xodev",
    "website": "https://github.com/OCA/currency",
    "license": "AGPL-3",
    "category": "Financial Management/Configuration",
    "summary": (
        "Disables Enterprise currency_rate_live automatic updates when "
        "OCA currency_rate_update is installed"
    ),
    "depends": [
        "currency_rate_update",
        "currency_rate_live",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "auto_install": ["currency_rate_update", "currency_rate_live"],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
