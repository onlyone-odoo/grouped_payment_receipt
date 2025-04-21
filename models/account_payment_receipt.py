from odoo import api, fields, models


class AccountPaymentReceipt(models.Model):
    _name = "account.payment.receipt"
    _description = "Grouped Payment Receipt"
    _order = "date desc, id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        string="Receipt Number",
        required=True,
        copy=False,
        readonly=True,
        default="New",
    )
    date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner",
        required=True,
    )
    payment_ids = fields.Many2many(
        comodel_name="account.payment",
        string="Payments",
        required=True,
    )
    payment_names = fields.Char(
        string="Original Payments",
        compute="_compute_payment_names",
        store=True,
    )
    move_ids = fields.Many2many(
        comodel_name="account.move",
        string="Invoices",
        required=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        compute="_compute_company",
        store=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        compute="_compute_currency",
        store=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("posted", "Posted"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="posted",
        required=True,
    )

    @api.depends("payment_ids")
    def _compute_payment_names(self):
        for record in self:
            record.payment_names = (
                ", ".join(record.payment_ids.mapped("name"))
                if record.payment_ids
                else ""
            )

    @api.depends("payment_ids")
    def _compute_company(self):
        for record in self:
            record.company_id = (
                record.payment_ids[:1].company_id if record.payment_ids else False
            )

    @api.depends("company_id")
    def _compute_currency(self):
        for record in self:
            record.currency_id = (
                record.company_id.currency_id if record.company_id else False
            )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if not self.partner_id:
            self.payment_ids = False
            self.move_ids = False
            return

        # Obtener pagos posteados del partner que aún no están en otro recibo
        used_payment_ids = self.env['account.payment.receipt'].search([]).mapped('payment_ids.id')

        available_payments = self.env['account.payment'].search([
            ('partner_id', '=', self.partner_id.id),
            ('state', '=', 'posted'),
            ('id', 'not in', used_payment_ids),
        ])

        # Obtener facturas relacionadas con esos pagos
        invoices = self.env['account.move']
        for payment in available_payments:
            payment_lines = payment.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
            )
            reconciliations = self.env['account.partial.reconcile'].search([
                '|',
                ('debit_move_id', 'in', payment_lines.ids),
                ('credit_move_id', 'in', payment_lines.ids),
            ])
            for reconciliation in reconciliations:
                invoice = (
                    reconciliation.credit_move_id.move_id
                    if reconciliation.debit_move_id in payment_lines
                    else reconciliation.debit_move_id.move_id
                )
                if invoice.is_invoice():
                    invoices |= invoice

        self.payment_ids = available_payments
        self.move_ids = invoices

    def get_payments_by_currency(self):
        """Return payments grouped by currency as a list of (currency, payments) tuples."""
        self.ensure_one()
        payments_by_currency = {}
        for payment in self.payment_ids.sorted(
            key=lambda p: (p.currency_id.name, p.date)
        ):
            currency_id = payment.currency_id.id
            if currency_id not in payments_by_currency:
                payments_by_currency[currency_id] = []
            payments_by_currency[currency_id].append(payment)

        result = []
        for currency_id, payments in payments_by_currency.items():
            currency = self.env["res.currency"].browse(currency_id)
            result.append((currency, payments))
        return result

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("account.payment.receipt")
                    or "New"
                )
        return super().create(vals_list)

    def action_post(self):
        self.write({"state": "posted"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_draft(self):
        self.write({"state": "draft"})

    def action_print_receipt(self):
        """Print the grouped payment receipt."""
        return self.env.ref(
            "grouped_payment_receipt.action_report_payment_receipt"
        ).report_action(self)
