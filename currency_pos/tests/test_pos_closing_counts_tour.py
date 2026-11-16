from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingHttpCommon
from odoo.addons.point_of_sale.tests.common import archive_products


@tagged("post_install", "-at_install", "currency_pos_tour")
class TestPosClosingCountedCashTour(AccountTestInvoicingHttpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # AccountTestInvoicingHttpCommon's acting user has no POS access at
        # all, so every pos.* create/read below raised AccessError before a
        # browser was ever started. Grant the same group core's own POS
        # tour base class (point_of_sale.tests.test_frontend.
        # TestPointOfSaleHttpCommon) grants its acting user.
        cls.env.user.group_ids += cls.env.ref("point_of_sale.group_pos_manager")
        archive_products(cls.env)
        cls.company_data["default_journal_cash"].pos_payment_method_ids.unlink()
        cls.cash_payment_method = cls.env["pos.payment.method"].create(
            {
                "name": "Cash",
                "journal_id": cls.company_data["default_journal_cash"].id,
                "receivable_account_id": cls.company_data["default_account_receivable"].id,
            }
        )
        cls.eur_currency = cls.env.ref("base.EUR")
        cls.eur_currency.active = True
        cls.env["res.currency.rate"].search([("currency_id", "=", cls.eur_currency.id)]).unlink()
        cls.env["res.currency.rate"].create(
            {
                "name": "2026-01-01",
                "rate": 2.0,
                "currency_id": cls.eur_currency.id,
            }
        )
        cash_journal = cls.company_data["default_journal_cash"]
        profit_account = (
            cash_journal.profit_account_id
            or cls.company.default_cash_difference_income_account_id
        )
        loss_account = (
            cash_journal.loss_account_id
            or cls.company.default_cash_difference_expense_account_id
        )
        if profit_account and not cash_journal.profit_account_id:
            cash_journal.profit_account_id = profit_account
        if loss_account and not cash_journal.loss_account_id:
            cash_journal.loss_account_id = loss_account
        cls.eur_cash_journal = cls.env["account.journal"].create(
            {
                "name": "Cash EUR Closing Tour",
                "type": "cash",
                "code": "CEUC",
                "currency_id": cls.eur_currency.id,
                "profit_account_id": profit_account.id if profit_account else False,
                "loss_account_id": loss_account.id if loss_account else False,
            }
        )
        cls.eur_cash_payment_method = cls.env["pos.payment.method"].create(
            {
                "name": "Cash EUR",
                "journal_id": cls.eur_cash_journal.id,
                "receivable_account_id": cls.company_data["default_account_receivable"].id,
            }
        )
        cls.main_pos_config = cls.env["pos.config"].create(
            {
                "name": "Tour POS Closing Counts",
                "journal_id": cls.company_data["default_journal_sale"].id,
                "invoice_journal_id": cls.company_data["default_journal_sale"].id,
                "allow_multi_currency_payment": True,
                "payment_method_ids": [
                    (4, cls.cash_payment_method.id),
                    (4, cls.eur_cash_payment_method.id),
                ],
            }
        )
        cls.tour_product = cls.env["product.product"].create(
            {
                "name": "Tour Closing Product",
                "available_in_pos": True,
                "list_price": 10.0,
                "taxes_id": [(6, 0, [])],
            }
        )
        cls.pos_user = cls.env["res.users"].create(
            {
                "name": "POS Closing MC User",
                "login": "pos_closing_mc_user",
                "password": "pos_closing_mc_user",
                # (6, 0, [...]) replaces the whole group_ids list, so
                # base.group_user must be included explicitly or this user
                # is not an internal user; point_of_sale.group_pos_user
                # does not imply it (only group_pos_manager does, plus
                # stock.group_stock_user). Without it, Odoo 19's
                # /pos/ui(/<id>) controllers 404 via
                # `if not is_internal_user: return request.not_found()`
                # before the tour's own page ever loads (core's own POS test
                # fixture, point_of_sale.tests.test_frontend.TestPointOfSaleHttpCommon,
                # grants these two plus stock.group_stock_user, which these tours
                # do not need).
                "group_ids": [
                    (
                        6,
                        0,
                        (
                            cls.env.ref("base.group_user")
                            + cls.env.ref("point_of_sale.group_pos_manager")
                        ).ids,
                    ),
                ],
            }
        )

    def test_closing_stores_counted_cash_of_every_method(self):
        """Close through the real UI: each cash box keeps the amount typed."""
        config = self.main_pos_config
        self.start_tour(
            f"/pos/ui?config_id={config.id}",
            "PosClosingCountedCashByMethodTour",
            login="pos_closing_mc_user",
        )
        sessions = self.env["pos.session"].search([("config_id", "=", config.id)], order="id")
        closed = sessions.filtered(lambda s: s.state == "closed")
        self.assertEqual(len(closed), 1, "The session must be closed from the UI")
        usd_box = closed._oca_get_cash_box(self.cash_payment_method)
        eur_box = closed._oca_get_cash_box(self.eur_cash_payment_method)
        self.assertAlmostEqual(usd_box.balance_end_real, 10.0, places=2)
        self.assertAlmostEqual(usd_box.closing_difference, 0.0, places=2)
        self.assertAlmostEqual(eur_box.balance_end_real, 8.0, places=2)
        # Nothing was paid in EUR, so everything counted there is a surplus.
        self.assertAlmostEqual(eur_box.closing_difference, 8.0, places=2)
        # Core's `router.close()` navigates to /pos/ui/<config>, which opens
        # the next session; it must be a fresh one, never the closed session.
        others = sessions - closed
        self.assertTrue(all(s.state == "opening_control" for s in others))
