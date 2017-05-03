# coding: utf-8
# © 2016 Akretion
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models, api, _
from odoo.exceptions import Warning


class PosInvoiceReport(models.AbstractModel):
    _inherit = 'report.point_of_sale.report_invoice'

    @api.multi
    def render_html(self, sale_id, data):
        report_obj = self.env['report']
        posorder_obj = self.env['sale.order']
        report = report_obj._get_report_from_name('account.report_invoice')
        selected_orders = posorder_obj.browse(sale_id)

        ids_to_print = []
        invoiced_posorders_ids = []
        invoice_to_print = []
        for order in selected_orders:
            if order.invoice_ids:
                ids_to_print.append(order.invoice_ids.id)
                invoiced_posorders_ids.append(order.id)
                invoice = self.env['account.invoice'].browse(
                    order.invoice_ids.id)
                invoice_to_print.append(invoice)

        not_invoiced_orders_ids = list(set() - set(invoiced_posorders_ids))
        if not_invoiced_orders_ids:
            not_invoiced_posorders = posorder_obj.browse(
                not_invoiced_orders_ids)
            not_invoiced_orders_names = list(
                map(lambda a: a.name, not_invoiced_posorders))
            raise Warning(
                _('Error!'),
                _('No link to an invoice for %s.' % ', '.
                  join(not_invoiced_orders_names)))

        docargs = {
            'doc_ids': ids_to_print,
            'doc_model': report.model,
            'docs': invoice_to_print,
        }
        return report_obj.render('account.report_invoice', docargs)
