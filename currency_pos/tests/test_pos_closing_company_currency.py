from odoo.tests import tagged

from .common import TestPosPaymentCurrencyCommon


@tagged("post_install", "-at_install", "currency_pos")
class TestPosClosingCompanyCurrency(TestPosPaymentCurrencyCommon):
    """POS in a currency (EUR) that is not the company currency (USD) with a
    payment method in the company currency: the usual Venezuelan setup, mirrored."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pos_eur_config = cls.other_currency_config
        cls.pos_eur_config.allow_multi_currency_payment = True
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.bank_journal.write(
            {
                "profit_account_id": cls.company.default_cash_difference_income_account_id.id,
                "loss_account_id": cls.company.default_cash_difference_expense_account_id.id,
            }
        )
        cls.company_bank_pm = cls.env["pos.payment.method"].create(
            {
                "name": "Bank company currency",
                "type": "bank",
                "journal_id": cls.bank_journal.id,
                "receivable_account_id": cls.pos_receivable_bank.id,
                "outstanding_account_id": cls.outstanding_bank.id,
            }
        )
        cash_journal = cls.env["account.journal"].create(
            {
                "name": "Cash company currency POS",
                "type": "cash",
                "code": "CCCP",
                "profit_account_id": cls.company.default_cash_difference_income_account_id.id,
                "loss_account_id": cls.company.default_cash_difference_expense_account_id.id,
            }
        )
        cls.company_cash_pm = cls.env["pos.payment.method"].create(
            {
                "name": "Cash company currency",
                "type": "cash",
                "journal_id": cash_journal.id,
                "receivable_account_id": cls.pos_receivable_cash.id,
            }
        )
        cls.pos_eur_config.payment_method_ids = [
            (4, cls.company_bank_pm.id),
            (4, cls.company_cash_pm.id),
        ]

    def _paid_session(self):
        self.config = self.pos_eur_config
        session = self.open_new_session(0)
        self.assertNotEqual(session.currency_id, session.company_id.currency_id)
        order_data = self.create_ui_order_data(
            [(self.product_mc, 1)], payments=[(self.company_bank_pm, 1.0)]
        )
        total = order_data["amount_total"]
        order_data["payment_ids"][0][2]["amount"] = total
        order_data["amount_paid"] = total
        self.env["pos.order"].sync_from_ui([order_data])
        payment = session.order_ids.payment_ids
        self.assertEqual(payment.payment_currency_id, session.company_id.currency_id)
        return session, payment

    def test_bank_difference_balance_is_in_company_currency(self):
        session, payment = self._paid_session()
        # Counted in the currency of the method (company currency): 5 missing.
        counted = payment.payment_currency_amount - 5.0
        session.close_session_from_ui(
            {
                str(self.cash_pm2.id): 0.0,
                str(self.company_bank_pm.id): counted,
            }
        )
        self.assertEqual(session.state, "closed")
        correction = session.correction_move_ids
        self.assertEqual(len(correction), 1)
        # The balance is the 5 company currency units, not 5 order currency units
        # taken as company currency.
        self.assertEqual(sorted(correction.line_ids.mapped("balance")), [-5.0, 5.0])
        self.assertEqual(correction.line_ids.mapped("currency_id"), session.currency_id)
        expected_order_amount = session.company_id.currency_id._convert(
            5.0, session.currency_id, session.company_id, correction.date
        )
        self.assertEqual(
            sorted(round(a, 2) for a in correction.line_ids.mapped("amount_currency")),
            [-round(expected_order_amount, 2), round(expected_order_amount, 2)],
        )
        self.assertIn(self.bank_journal.loss_account_id, correction.line_ids.account_id)

    def test_exact_count_books_no_bank_difference(self):
        session, payment = self._paid_session()
        session.close_session_from_ui(
            {
                str(self.cash_pm2.id): 0.0,
                str(self.company_bank_pm.id): payment.payment_currency_amount,
            }
        )
        self.assertEqual(session.state, "closed")
        self.assertFalse(session.correction_move_ids)

    def test_cash_box_difference_is_booked_in_the_box_currency(self):
        """The cash box in the company currency of a POS in EUR: the difference is a
        statement line of its journal, in its currency, with the same balance."""
        self.config = self.pos_eur_config
        session = self.open_new_session(0)
        box = session._oca_get_cash_box(self.company_cash_pm)
        box.balance_start = 10.0
        session.close_session_from_ui(
            {
                str(self.cash_pm2.id): 0.0,
                str(self.company_cash_pm.id): 8.0,
            }
        )
        self.assertEqual(session.state, "closed")
        self.assertAlmostEqual(box.closing_difference, -2.0, places=2)
        line = session._oca_statement_lines(self.company_cash_pm.journal_id)
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.amount, -2.0, places=2)
        self.assertAlmostEqual(line.move_id.line_ids.filtered("balance")[:1].balance, -2.0, places=2)
        self.assertFalse(line.foreign_currency_id)

    def test_bank_overcount_is_a_profit_in_company_currency(self):
        session, payment = self._paid_session()
        counted = payment.payment_currency_amount + 5.0
        session.close_session_from_ui(
            {
                str(self.cash_pm2.id): 0.0,
                str(self.company_bank_pm.id): counted,
            }
        )
        self.assertEqual(session.state, "closed")
        correction = session.correction_move_ids
        self.assertEqual(len(correction), 1)
        self.assertEqual(sorted(correction.line_ids.mapped("balance")), [-5.0, 5.0])
        self.assertIn(self.bank_journal.profit_account_id, correction.line_ids.account_id)
        self.assertNotIn(self.bank_journal.loss_account_id, correction.line_ids.account_id)

    def test_non_foreign_bank_difference_is_booked_in_company_currency(self):
        """A bank method in the POS currency (EUR journal) counted in that currency:
        core would book the EUR difference as company currency."""
        eur_journal = self.env["account.journal"].create(
            {
                "name": "Bank EUR company check",
                "type": "bank",
                "code": "BEUC",
                "currency_id": self.other_currency.id,
                "profit_account_id": self.company.default_cash_difference_income_account_id.id,
                "loss_account_id": self.company.default_cash_difference_expense_account_id.id,
            }
        )
        eur_bank_pm = self.env["pos.payment.method"].create(
            {
                "name": "Bank EUR same as POS",
                "type": "bank",
                "journal_id": eur_journal.id,
                "receivable_account_id": self.pos_receivable_bank.id,
                "outstanding_account_id": self.outstanding_bank.id,
            }
        )
        self.pos_eur_config.payment_method_ids = [(4, eur_bank_pm.id)]
        self.config = self.pos_eur_config
        session = self.open_new_session(0)
        self.assertEqual(eur_bank_pm.payment_currency_id, session.currency_id)
        order_data = self.create_ui_order_data([(self.product_mc, 1)], payments=[(eur_bank_pm, 1.0)])
        total = order_data["amount_total"]
        order_data["payment_ids"][0][2]["amount"] = total
        order_data["amount_paid"] = total
        self.env["pos.order"].sync_from_ui([order_data])
        # 10.00 EUR missing, i.e. 5.00 in the company currency (1 company unit = 2 EUR).
        session.close_session_from_ui(
            {str(self.cash_pm2.id): 0.0, str(eur_bank_pm.id): total - 10.0}
        )
        self.assertEqual(session.state, "closed")
        correction = session.correction_move_ids
        self.assertEqual(len(correction), 1)
        self.assertEqual(sorted(correction.line_ids.mapped("balance")), [-5.0, 5.0])
        self.assertEqual(
            sorted(round(a, 2) for a in correction.line_ids.mapped("amount_currency")),
            [-10.0, 10.0],
        )
        self.assertEqual(correction.line_ids.mapped("currency_id"), session.currency_id)

