
from odoo import fields, api, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    _sql_constraints = [('pos_reference_uniq',
                         'unique (pos_reference, session_id)',
                         'The pos_reference must be uniq per session')]

    pos_reference = fields.Char(string='Receipt Ref',
                                readonly=True,
                                copy=False,
                                default='')

    payment_ids = fields.Many2many(comodel_name= 'account.payment',readonly=True)
    session_id = fields.Many2one(comodel_name='pos.order',
                                 string='Session',
                                 domain="[('state', '=', 'opened')]",
                                 states={'draft': [('readonly', False)]},
                                 readonly=True)

    @api.multi
    def confirm_sale_from_pos(self):
        " Make sale confirmation optional "
        self.ensure_one()
        return True


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    session_id = fields.Many2one(comodel_name='sale.order',
                                 string='Session',
                                 domain="[('state', '=', 'opened')]",
                                 states={'draft': [('readonly', False)]},
                                 readonly=True)
