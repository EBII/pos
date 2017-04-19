# coding: utf-8
# © 2015 Valentin CHEMIERE @ Akretion
# © 2015 Chafique DELLI @ Akretion
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import re
from openerp import models, api, fields, _
from openerp.exceptions import Warning as UserError, ValidationError
from openerp.addons.product.product import ean_checksum
from openerp.tools import (
    DEFAULT_SERVER_DATETIME_FORMAT,
    DEFAULT_SERVER_DATE_FORMAT,
    )
from datetime import datetime, timedelta
from openerp.osv import fields as oldFields
import logging
import copy
_logger = logging.getLogger(__name__)


HELP_REQUESTED_DATE = (
    u"Date de mise à disposition soit demandée par le client "
    u"soit calculer (en cliquant sur le bouton) en tenant compte du "
    u"délai le plus grand pour chaque ligne, de l'urgence de la "
    u"commande et des jours ouvrés de la société")

#M704_DELAY = 60

STATUS = [
    ('cancel', 'Annulé'),
    #('draft', 'Devis'),
    # ('pending_purchase_m704', 'Attente Prise de Commande Marck'),
    #('pending_receive_m704', 'Attente Recep. Marck'),
    #('in_production', 'En Prod'),
    ('available', 'Mise à dispo'),
    ('delivered', 'Livré')
]


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # Patch to avoid security issue (should be remove after odoo update)
 #   product_tmpl_id = fields.Many2one(readonly=True)
    # PATCH END
    # allow to edit the product and the price
    # product_id = fields.Many2one(readonly=False)
    # price_unit = fields.Float(readonly=False)
    # product_uom_qty = fields.Float(readonly=False)
    # product_uos_qty = fields.Float(readonly=False)
    #
    price_with_material = fields.Boolean()
    urgent = fields.Boolean(related='order_id.urgent',
                            string='Commande Urgente', readonly=True)
    # amount_penalty = fields.Float(
    #     string="Pénalité de retard",
    #     compute='_compute_penalty', store=True,
    #     help="Montant de la pénalité de retard en H.T.")
    # discount = fields.Float(readonly=False)
    # section_id = fields.Many2one(
    #     related='order_id.section_id',
    #     string='Marché',
    #     readonly=True)
    # m704 = fields.Boolean(
    #     u'Marché M704',
    #     compute='_compute_m704',
    #     store=True)

    # We only recompute when updating the delay to avoid useless recomputation
    # @api.depends('order_id.delay')
    # def _compute_penalty(self):
    #     for line in self:
    #         penalty = 0.0
    #         if line.order_id.section_id == self.env.ref(
    #                 'custom.section_sales_department_mindef'):
    #             if line.order_id.delay and line.order_id.deadline_id:
    #                 penalty = ((line.order_id.delay * line.price_subtotal) /
    #                            line.order_id.deadline_id.penalty)
    #                 if line.order_id.urgent:
    #                     penalty = penalty * 2
    #             if penalty == 0:
    #                 continue
    #             if penalty > line.price_subtotal:
    #                 line.amount_penalty = line.price_subtotal
    #             else:
    #                 line.amount_penalty = penalty
    #
    # @api.depends('product_id')
    # def _compute_m704(self):
    #     """Cache m704 on the line for quicker report processing."""
    #     for line in self:
    #         line.m704 = line.product_id.m704

    def product_id_change_with_wh(
            self, cr, uid, ids, pricelist, product, qty=0, uom=False,
            qty_uos=0, uos=False, name='',
            partner_id=False, lang=False,
            update_tax=True, date_order=False,
            packaging=False, fiscal_position=False,
            flag=False, warehouse_id=False, context=None,
            price_with_material=False,
            urgent=False):
        if context:
            newcontext = context.copy()
            newcontext['with_rm'] = price_with_material
            newcontext['urgent'] = urgent
        else:
            newcontext = context
        res = {'value': {}}
        if product:
            res = super(SaleOrderLine, self).product_id_change_with_wh(
                cr, uid, ids,
                pricelist=pricelist, product=product, qty=qty, uom=uom,
                qty_uos=qty_uos, uos=uos, name=name, partner_id=partner_id,
                lang=lang, update_tax=update_tax, date_order=date_order,
                packaging=packaging, fiscal_position=fiscal_position,
                flag=flag, warehouse_id=warehouse_id, context=newcontext)

        # TODO hotfix for solving issue with taxes
        # in multi company mode with shared of taxe
        # we should replace the tax field by a related or a computed field
        prd = self.pool['product.product'].browse(cr, uid, product, newcontext)
        taxes = prd.tax_group_id.customer_tax_ids
        if taxes:
            res['value']['tax_id'] = [taxes[0].id]
        if fiscal_position:
            fiscal_obj = self.pool['account.fiscal.position']
            fpos = fiscal_obj.browse(cr, uid, fiscal_position, context=context)
            res['value']['tax_id'] = fiscal_obj.map_tax(
                cr, uid, fpos, taxes, context=context)
        # Always remove pop up warning
        if 'warning' in res:
            res.pop('warning')
        return res

    # @api.onchange('price_with_material')
    # def price_with_material_change(self):
    #     res = self.product_id_change_with_wh(
    #         self.order_id.pricelist_id.id,
    #         self.product_id.id,
    #         qty=self.product_uom_qty,
    #         uom=False,
    #         qty_uos=self.product_uos_qty,
    #         uos=False,
    #         name=self.name,
    #         partner_id=self.order_id.partner_id.id,
    #         lang=False,
    #         update_tax=True,
    #         date_order=self.order_id.date_order,
    #         packaging=False,
    #         fiscal_position=self.order_id.fiscal_position,
    #         flag=True,
    #         warehouse_id=self.order_id.warehouse_id.id,
    #         price_with_material=self.price_with_material,
    #         urgent=self.order_id.urgent,
    #     )
    #     if res:
    #         vals = res['value']
    #         for k, v in vals.iteritems():
    #             self[k] = v

    @api.multi
    def _get_max_deadline(self):
        self.ensure_one()
        max_deadline = self.product_id.get_deadline(self.product_uom_qty)
        for option in self.optional_bom_line_ids:
            qty = self.product_uom_qty * option.qty
            deadline = option.bom_line_id.product_id.get_deadline(qty)
            if not max_deadline or (
                    deadline and deadline.deadline > max_deadline.deadline):
                max_deadline = deadline
        return max_deadline

    @api.model
    def _check_exception_no_measure_for_product(self):
        if (self.need_measure and self.order_id.company_id and
                self.order_id.company_id.wait_for_measure and not
                self.order_id.ignore_exceptions):
            return True
        return False

    @api.model
    def _prepare_order_line_invoice_line(self, line, account_id=False):
        #TODO maybe will should extract the categ management of account
        if not line.product_id and not account_id:
            account = self.env['account.account'].search([
                ('code', '=', '701100'),
                ])
            account_id = account.id
        return super(SaleOrderLine, self)._prepare_order_line_invoice_line(
            line, account_id=account_id)

    @api.multi
    def unlink(self):
        for record in self:
            if record.order_id.invoice_state not in ('pending', 'invoiced'):
                # We force the state of the line to cancel in order to
                # be able to remove the line on the sale order
                # this is a necessary hack as Abilis prefer to drop
                # line and have inconsitent data then to recreate the sale
                # order
                # TODO refactor me on 9 as this version allow to edit sale
                # order
                record.write({'state': 'cancel'})
        return super(SaleOrderLine, self).unlink()

class AbstractEAN13(models.AbstractModel):
    _name = 'abstract.ean13'

    @api.model
    def _build_ean13(self, company_id, name):
        if name == '/' or not name:
            return
        code = '%02i' % company_id
        m = re.search('[^\d*](\d{7})$', name)
        if m:
            code += '%s000' % m.group(1)
        else:
            m = re.search('[^\d*](\d{7})-(\d{2})', name)
            if m:
                code += '%s%s0' % (m.group(1), m.group(2))
            else:
                m = re.search('[^\d*](\d{7})-(\d{2})-(\d{1})', name)
                if m:
                    code += '%s%s%s' % (
                        m.group(1),
                        m.group(2),
                        m.group(3),
                    )
                else:
                    _logger.error('EAN13: Invalid name format ("%s") !'
                                  'Skip creattion', name)
        return code + str(ean_checksum(code+'0'))

    @api.one
    @api.depends('name')
    def _compute_ean13(self):
        if self._context.get('force_company'):
            company_id = self._context['force_company']
        elif 'company_id' in self._fields and self.company_id:
            company_id = self.company_id.id
        else:
            company_id = self.env.user.company_id.id
        self.ean13 = self._build_ean13(company_id, self.name)


class MixinSaleOrder(models.AbstractModel):
    _name = 'mixin.sale.order'

    @api.model
    def get_sale_status(self):
        return STATUS


class SaleOrder(models.Model):
    _inherit = ['mixin.sale.order', 'sale.order',
                'abstract.activity', 'abstract.ean13']
    _name = 'sale.order'
    _order = 'date_order desc, name desc'

    def _get_default_section(self):
        return self.env.ref('custom.section_sales_department_mindef')

    # Redifined this two field as we do not need it and as there as
    # recomputed all of the time for nothing
    # We should really try do drop the sale_order_dates module
    _columns = {
        'effective_date': oldFields.date(),
        'commitment_date': oldFields.date(),
        }
    ##
    check_message = fields.Boolean(default=False)
    pricelist_id = fields.Many2one(readonly=False)
    external_lot_ref = fields.Char(string=u"Réf. Marck/M704")
    ean13 = fields.Char(
        'Code Barre',
        help=u"Code EAN13, recherche possible via le nom "
             u"(via douchette ou zone de recherche)",
        compute='_compute_ean13', store=True
    )
    next_state_id = fields.Many2one(
        string='Prochain Statut', related='partner_id.next_state_id')
    use_next_state = fields.Boolean(string="Utiliser le prochain statut")
    partner_view_xmlid = fields.Char(compute='_get_view_xmlid')
    section_id = fields.Many2one(
        default=_get_default_section,
        select=True)
    urgent = fields.Boolean(string='Commande Urgente',
                            readonly=True, default=False,
                            states={'draft': [('readonly', False)],
                                    'sent': [('readonly', False)]})
    requested_date = fields.Date(
        string="Date d'exigibilité",
        copy=False,
        help=HELP_REQUESTED_DATE,
        select=True)
    deadline_id = fields.Many2one(
        'deadline.type',
        string=u'Délai Mindef',
        compute='_compute_deadline')
    delivery_now = fields.Boolean('Livraison Immédiate')
    workflow_process_id = fields.Many2one(
        'sale.workflow.process',
        string='Workflow Process',
        ondelete='restrict',
        compute='_compute_workflow_process',
        store=True,
        readonly=True)
    is_quotation = fields.Boolean(
        'Devis nécessitant une validation mindef',
        readonly=True,
        default=False)
    decision_rla = fields.Boolean('Décision rla', readonly=True)
    decision_cescof = fields.Boolean(u'Décision cescof', readonly=True)
    date_order = fields.Datetime(
        states={},
        readonly=False,
        select=True)
    date_delivered = fields.Date(
        'Retrait effectué',
        copy=False,
        select=True)
    date_assigned = fields.Date(
        'Mise à disposition',
         copy=False,
         select=True)
    date_purchased = fields.Date(
        'Commandé (Marck/M704)',
        copy=False,
        select=True)
    date_received = fields.Date(
        'Reçu (Marck/M704)',
        copy=False,
        select=True)
    date_decision_rla = fields.Date(
        'Date prise décision RLA',
        readonly=True,
        copy=False)
    date_decision_cescof = fields.Date(
        'Date prise décision Cescof',
        readonly=True,
        copy=False)
    date_quotation_proposed = fields.Date(
        'Date proposition au mindef',
        readonly=True,
        copy=False)
    delay = fields.Integer(
        string=u'Jours de retard',
        help=u'Nombre de jours de retard',
        compute='_compute_delay',
        store=True)
    m704 = fields.Boolean(
        u'Marché M704',
        compute='_compute_m704',
        help='Comporte au moins un article du m704',
        store=True)
    manual_exception = fields.Text(
        readonly=True,
        help="Permet au groupe Abilis de bloquer la facturation pour un "
             "motif particulier (non récurrent)")
    signature_img = fields.Binary(
        string='Image signature',
        readonly=True)
    # Even if the status field is a computed field we need to add a default
    # value so the autohide filter (hide cancel)  will not hide it before
    # the field is computed
    status = fields.Selection(
        selection='get_sale_status',
        compute='_compute_status',
        default='draft',
        store=True)
    invoice_state = fields.Selection(
        help="Statut de facturation. Dans le cas du MinDef pour que la vente "
             "soit facturable il faut qu'elle soit mise à dispo "
             "depuis 15 jours ou livrée")
    auto_message = fields.Text(compute='_compute_auto_message')
    processing_time = fields.Integer(
        string='Temps de traitement',
        help="Entre la saisie et la mise à disposition au client",
        compute='_compute_processing_time',
        store=True)
    blocked = fields.Boolean(
        'Bloqué', readonly=True,
        help="Used to compute invoice state",
        oldname="not_invoiceable")
    amount_penalty = fields.Float(
        string=u"Pénalité de retard",
        help=u'Montant de la pénalité de retard (H.T.)',
        compute='_compute_penalty',
        store=True)
    force_cancel = fields.Boolean(
        string=u"Forcer l'annulation de la vente", copy=False)
    partner_ref = fields.Char(string='Client Ref', related='partner_id.ref')
    partner_name = fields.Char(string='Client Name', related='partner_id.name')
    user_defined_type = fields.Selection([
        ('ecole', 'Ecole'),   # uniquement certaines écoles sinon incorpo
        ('incorpo_mdr_mta', 'Incorporation MDR MTA'),  # uniquement MTA et MDR
        ('incorpo_autre', 'Autres incorpo'),  # autres incorpos
        ('collectif', 'Collectif'), # autre collectif
        ('indiv', 'Individuelle'),
        ],
        string="Type indiqué par le vendeur",
        # reseigné dans le POS
        # redondant avec d'aurtres infos saisies par ailleurs
        # permet de faire des stats pour le mindef
        # l'information du M704 est ajoutée par _compute_m704
        help=u"Information complémentaire saisie via le POS")
    xml_sale_receipt = fields.Text(string='XML Sale receipt')
    force_activity_code = fields.Selection(
        string="Forcer le code d'activité",
        selection=[
            ('habillement', 'Habillement'),
            ('0178080201D1', "1D1-Soutien de l'homme"),
            ], help="Permet de forcer le code d'activité")
    activity_code = fields.Selection(
        compute='_compute_activity_code', store=True)
    without_bon_confection = fields.Boolean(
        'Sans bon',
        help=(u"Si coché, la commande n'a pas de bon de confection requis. "
              u"dans ce cas elle sera envoyée par email au RLA afin qu'il"
              u"puisse suivre les commandes faites sans bon"))
    without_bon_confection_payment = fields.Selection([
        ('gratuit', 'Gratuit'),
        ('compte_points', 'Points'),
    ], string='Paiement sans bon')
    without_bon_confection_export = fields.Date(
        string='Date export sans bon',
        help=u"Date a laquel la commande sans bon à été transférer au RLA "
             u"par email")
    session_id = fields.Many2one(copy=False)
    rla_id = fields.Many2one(
        'res.partner',
        string=u'RLA',
        compute='_compute_rla',
        store=True)
    with_bom_line = fields.Boolean(compute='_compute_with_bom_line',
                                   string='With Bom Line')
    order_line = fields.One2many(
        readonly=False, states={'done': [('readonly', True)]})
    amount_untaxed = fields.Float(track_visibility='always')

    # Partner field stored on sale order
    # This field do not change if the partner profile change
    gsbdd_id = fields.Many2one(
        'res.partner',
        'Gsbdd',
        compute='compute_partner_fields',
        store=True)
    corps_id = fields.Many2one(
        'product.attribute.value',
        'Corps',
        compute='compute_partner_fields',
        store=True)

    # Field for checking order validation

    invalid_qty = fields.Boolean(
        compute='_compute_invalid_qty',
        store=True, compute_sudo=True,
        help="Ce champ indique si la quantité d'une des lignes "
             "d'options est supérieur à la quantité max autorisée.")
    invalid_amount = fields.Boolean(
        compute='_compute_invalid_amount',
        store=True,
        help="Ce champ indique si le montant d'une ligne "
             "est à zéro ou négatif.")

    @api.multi
    @api.depends('order_line.optional_bom_line_ids.invalid_qty')
    def _compute_invalid_qty(self):
        for record in self:
            record.invalid_qty = False
            for line in record.order_line:
                for option in line.optional_bom_line_ids:
                    if option.invalid_qty:
                        record.invalid_qty = True
                        break

    @api.multi
    @api.depends(
        'order_line.price_unit',
        'order_line.product_id')
    def _compute_invalid_amount(self):
        for record in self:
            record.invalid_amount = False
            for line in record.order_line:
                if line.price_unit <=0 and not line.product_id.free_mindef:
                    record.invalid_amount = True
                    break

    @api.multi
    @api.depends('partner_id')
    def compute_partner_fields(self):
        for record in self:
            if record.partner_id:
                record.gsbdd_id = record.partner_id.get_gsbdd()
                record.corps_id = record.partner_id.corps_id \
                    or record.gsbdd_id.corps_id

    @api.model
    def get_name_ean13(self):
        name = self.env['ir.sequence'].get('sale.order')
        res = {
            'name': name,
            'ean13': self._build_ean13(self.env.user.company_id.id, name),
        }
        return res

    @api.multi
    def check_sent_message(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window',
                'res_model': 'sms.sms',
                'res_id': self.get_sms_record(self.id),
                'view_type': 'form',
                'view_mode': 'form',
                'target': 'new',
                'context': {'read': True}
                }

    @api.model
    def get_sms_record(self, sale_id):
        record = self.env['sms.sms'].search([('sale_id', '=', sale_id)])
        return record.id

    @api.model
    def _get_date_planned(self, order, line, start_date):
        if order and order.requested_date:
            date_planned = datetime.strptime(
                order.requested_date, DEFAULT_SERVER_DATE_FORMAT)
            return date_planned.strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        return super(SaleOrder, self)._get_date_planned(
            order, line, start_date)

    @api.model
    def _prepare_vals_lot_number(self, order_line, index_lot):
        """Prepare values before creating a lot number"""
        vals = super(SaleOrder, self)._prepare_vals_lot_number(
            order_line, index_lot)
        if self.partner_id and self.partner_id.kind == 'individu':
            partner = self.partner_id
            vals.update({
                'arme_id': partner.arme_id.id,
                'arme_origin_id': partner.arme_origin_id.id,
                'grade_id': self.partner_id.grade_id.id,
                'affectation_id': partner.affectation_id.id,
                })
        vals.update({
            'measure_id': order_line.measure_id.id,
            'sale_id': self.id,
            })
        return vals

    @api.multi
    @api.onchange('delivery_now')
    def onchange_delivery_now(self):
        for record in self:
            if self.delivery_now:
                date = datetime.today()
                record.requested_date = date
                record.date_assigned = date

    # TODO move in a generic module
    @api.multi
    @api.onchange('section_id')
    def onchange_section_id(self):
        for record in self:
            if record.section_id:
                record.pricelist_id = record.section_id.pricelist_id
                record.fiscal_position = record.section_id.fiscal_position_id
                if record.section_id.section_partner_invoice_id:
                    record.partner_invoice_id = record.partner_id.id
            else:
                record.partner_invoice_id = record.partner_id.id

    # TODO move in a generic module
    @api.multi
    def onchange(self, values, field_name, field_onchange):
        # To avoid hard inheriting on partner_id we always play the section_id
        if isinstance(field_name, list) and 'section_id' in field_name:
            field_name.remove('section_id')
            field_name.append('section_id')
        # If we call an onchange on the partner_id we also call the onchange
        # on the section_id for the compatibility
        if field_name == 'partner_id':
            field_name = ['partner_id', 'section_id']
        return super(SaleOrder, self).onchange(
            values, field_name, field_onchange)

    @api.one
    def _get_view_xmlid(self):
        """Allow to choose what form is required according to partner kind"""
        if (self.partner_id.kind and
                self.partner_id.kind in ['individu', 'rla']):
            self.partner_view_xmlid = 'custom.view_partner_form_customer'
        else:
            self.partner_view_xmlid = 'custom.view_partner_form'

    @api.multi
    def _compute_auto_message(self):
        for record in self:
            group = self.env.ref('custom.group_custom_invoice_shooter')
            users = [user.name for user in group.users if user.id != 1]
            names = ', '.join(users)
            if record.force_cancel:
                record.auto_message = (
                    "L'annulation de la commande à été forcée car le traitement"
                    " de celle-ci à été commencé avant l'annulation.\n"
                    "Vous ne pouvez pas remettre en brouillon cette commande\n"
                    "Mais vous pouvez la désannuller")
            elif record.invoice_state == 'pending':
                record.auto_message = (
                    u"La commande est en cours de facturation et ne peut être "
                    u"modifiée, annulée ou bloquée.\nEn cas d'erreur veuillez "
                    u"contacter les personnes responsables de la facturation :"
                    u"\n%s" % names)
            elif record.invoice_state == 'invoiced':
                record.auto_message = \
                    u"La commande Facturé, elle n'est donc plus éditable"

    @api.one
    @api.depends(
        'order_line.product_id',
        'order_line.product_uom_qty',
        'order_line.optional_bom_line_ids')
    def _compute_deadline(self):
        max_deadline = None
        for line in self.order_line:
            deadline = line._get_max_deadline()
            if (deadline and (not max_deadline or
                              deadline.deadline > max_deadline.deadline)):
                max_deadline = deadline
        if not max_deadline:
            max_deadline = self.env['deadline.type'].search([
                ('name', '=', 'T1')])
        self.deadline_id = max_deadline

    @api.depends('order_line', 'order_line.optional_bom_line_ids')
    @api.multi
    def _compute_with_bom_line(self):
        for order in self:
            for line in order.order_line:
                if line.optional_bom_line_ids:
                    order.with_bom_line = True
                    break

    @api.depends('order_line.product_id', 'force_activity_code')
    @api.multi
    def _compute_activity_code(self):
        for sale in self:
            if sale.force_activity_code == '0178080201D1':
                sale.activity_code = '0178080201D1'
            elif sale.force_activity_code == 'habillement':
                # a sale order without code is a "habillement"
                sale.activity_code = None
            else:
                for line in sale.order_line:
                    code = line.product_id.activity_code\
                        or line.product_id.activity_code_rel
                    if code:
                        sale.activity_code = code
                        break

    @api.constrains(
        'date_order',
        'date_purchased',
        'date_received',
        'date_assigned',
        'date_delivered',
        'requested_date')
    @api.multi
    def _check_date(self):
        u"""Éviter les dates incohérentes ou improbables.

        Raise ValidationError en cas d'erreurs -> blocage de l'enregistrement
        Il peut y avoir des sales_exceptions complémentaires.
        """
        date_str = 0
        label = 1

        for sale in self:
            date_order = sale.date_order[0:10]
            dates = [
                (date_order, u'Date de commande'),
                (sale.date_purchased, u'Date de commandé (Mark)'),
                (sale.date_received, u'Date Reçu Mark'),
                (sale.date_assigned, u'Mise à disposition'),
                (sale.date_delivered, u'Retrait effectué'),
            ]

            # ensure date_order is not before project starting date
            if date_order < "2015-09-01":
                raise ValidationError(
                    u'La date de commande ne peut '
                    u'être trop loin dans le passé')

            # ensure date_order is not too in the future
            next_year = (
                datetime.today() + timedelta(days=365)
            ).strftime('%Y')
            if date_order > next_year:
                raise ValidationError(
                    u'La date de commande ne peut '
                    u'être trop loin dans le futur')

            # ensure date ordering. ex: can't deliver before order
            previous_date = dates[0]
            for date in dates[1:]:
                # date[date_str] may be false ! (undefined)
                if date[date_str]:
                    if previous_date[date_str] > date[date_str]:
                        # "something" > False == True
                        raise ValidationError(
                            u'La %s doit être postérieure à la %s'
                            % (date[label], previous_date[label]))
                    previous_date = date

            # check exigibility date
            if (sale.requested_date and
                    sale.requested_date < date_order):
                raise ValidationError(
                    u'La date demandée doit être postérieure à la commande')

    @api.depends('date_order', 'date_assigned', 'date_received')
    def _compute_processing_time(self):
        for record in self:
            if not record.date_assigned or not record.date_order:
                record.processing_time = 0
                continue
            if record.m704:
                if not record.date_received:
                    record.processing_time = 0
                    continue
                else:
                    start = datetime.strptime(
                        record.date_received,
                        DEFAULT_SERVER_DATE_FORMAT)
            else:
                start = datetime.strptime(
                    record.date_order, DEFAULT_SERVER_DATETIME_FORMAT)
            stop = datetime.strptime(
                record.date_assigned, DEFAULT_SERVER_DATE_FORMAT)
            calendar = self.env.ref('custom.timesheet_group1')
            record.processing_time = calendar.get_working_days(
                start, stop)[0]

    @api.depends(
        'date_delivered',
        'date_assigned',
        'date_purchased',
        'date_received',
        'm704',
        'state',
        'force_cancel')
    @api.multi
    def _compute_status(self):
        # TODO traiter le cas du BL transfered et de la sale 'mise à dispo'
        # la date de retrait est vide: informez l'utilisateur de l'incohérence
        for record in self:
            if record.state == 'cancel' or record.force_cancel:
                record.status = 'cancel'
            elif record.state in ('draft', 'sent'):
                record.status = 'draft'
            elif not record.date_assigned:
                # TODO for now we hide the step pending_purchase_m704
                if False:  # record.m704 and not record.date_purchased:
                    record.status = 'pending_purchase_m704'
                elif record.m704 and not record.date_received:
                    record.status = 'pending_receive_m704'
                else:
                    record.status = 'in_production'
            elif not record.date_delivered:
                record.status = 'available'
            else:
                record.status = 'delivered'

    @api.model
    def search_read_orders_reprint(self, query):
        domain = []
        if (query):
            domain += [
                '|',
                '|',
                ('partner_ref', 'ilike', query),
                ('partner_name', 'ilike', query),
                ('name', 'ilike', query),
            ]
        fields = [
            'id', 'date_order', 'name', 'partner_name',
            'partner_ref', 'amount_total',
        ]
        return self.search_read(
            domain, fields, order='date_order desc', limit=10)

    @api.one
    def load_xml_sale_receipt(self):
        return {
            'xml_sale_receipt': self.xml_sale_receipt,
        }

    @api.one
    @api.depends('order_line.product_id')
    def _compute_m704(self):
        for line in self.order_line:
            if line.m704:
                self.m704 = True
                return
        self.m704 = False

    @api.one
    @api.depends('delivery_now', 'session_id',
                 'is_quotation', 'decision_cescof')
    def _compute_workflow_process(self):
        # TODO add direct sale flow
        if self.is_quotation:
            # Note : we do not care of rla decision ;)
            if self.decision_cescof:
                # quote can now be transformed in order
                self.workflow_process_id = self.env.ref(
                    'custom.mindef_automatic_validation').id
            else:  # still not valid
                self.workflow_process_id = self.env.ref(
                    'custom.mindef_manual_validation').id
        else:
            if self.delivery_now:
                self.workflow_process_id = self.env.ref(
                    'custom.mindef_automatic_delivery').id
            elif self.session_id:
                self.workflow_process_id = self.env.ref(
                    'custom.mindef_automatic_validation').id
            else:
                self.workflow_process_id = self.env.ref(
                    'custom.mindef_manual_validation').id

    @api.one
    def compute_requested_date(self):
        if not self.order_line:
            raise UserError(u'Vous ne pouvez pas calculer la date demandée'
                            u' sans ligne de commande')
        if self.urgent:
            max_delay = self.deadline_id.urgent_deadline
        else:
            max_delay = self.deadline_id.deadline
        if self.m704:
            max_delay += M704_DELAY
        calendar = self.env.ref('custom.timesheet_group1')
        self.requested_date = calendar._get_date(
            start_date=self.date_order[0:10],
            delay=max_delay,
            resource_id=False)

    @api.depends('order_line.amount_penalty')
    def _compute_penalty(self):
        ''' Marché MinDef penalty '''
        for sale in self:
            if sale.delay:
                sale.amount_penalty = \
                    sum([l.amount_penalty for l in sale.order_line])

    @api.multi
    @api.depends('requested_date', 'date_assigned')
    def _compute_delay(self):
        for sale in self:
            sale.delay = 0
            if sale.section_id == self.env.ref(
                    'custom.section_sales_department_mindef'):
                if (sale.requested_date and
                        sale.date_assigned > sale.requested_date):
                    requested_date = datetime.strptime(
                        sale.requested_date, DEFAULT_SERVER_DATE_FORMAT)
                    date_assigned = datetime.strptime(
                        sale.date_assigned, DEFAULT_SERVER_DATE_FORMAT)
                    calendar = self.env.ref('custom.timesheet_group1')
                    sale.delay = calendar.get_working_days(
                        requested_date, date_assigned)[0]

    @api.one
    @api.depends('status', 'section_id.holding_company_id', 'date_assigned')
    def _compute_invoice_state(self):
        date_filter = datetime.now() - timedelta(days=15)
        date_filter = date_filter.strftime(DEFAULT_SERVER_DATE_FORMAT)
        mindef_section = self.env.ref('custom.section_sales_department_mindef')
        super(SaleOrder, self)._compute_invoice_state()
        for sale in self:
            if sale.status == 'delivered' and not (
                    sale.holding_invoice_id
                    or sale.invoice_ids):
                sale.invoice_state = 'invoiceable'
            if sale.status == 'cancel':
                sale.invoice_state = 'none'
            elif (
                    sale.section_id == mindef_section
                    and sale.status == 'available'
                    and sale.date_assigned <= date_filter):
                sale.invoice_state = 'invoiceable'

    @api.model
    def trigger_invoice_state(self):
        "Recherche des sales à passer en facturable"
        limit = datetime.now() - timedelta(days=15)
        domain = [
            ('invoice_state', '=', 'not_ready'),
            ('date_assigned', '<=',
                limit.strftime(DEFAULT_SERVER_DATE_FORMAT)),
            ]
        sales = self.search(domain)
        sales._compute_invoice_state()
        return True

    @api.model
    def compute_pos_requested_date(self, data):
        max_deadline = None
        allow_delivery_now = True

        def get_max_deadline(deadline, product, qty):
            new_deadline = product.get_deadline(qty)
            if not deadline or (new_deadline and
                                new_deadline.deadline > deadline.deadline):
                return new_deadline
            else:
                return deadline

        def can_be_delivered_now(allow_delivery, product):
            route = self.env.ref('mrp.route_warehouse0_manufacture')
            if route in product.route_ids:
                return False
            return allow_delivery
        m704 = False
        for line in data:
            product = self.env['product.product'].browse(line['id'])
            if product.m704:
                m704 = True
            max_deadline = get_max_deadline(
                max_deadline, product, line['quantity'])
            allow_delivery_now = can_be_delivered_now(
                allow_delivery_now, product)

            for option in line.get('operations', []):
                product = self.env['product.product'].browse(option['id'])
                max_deadline = get_max_deadline(
                    max_deadline, product,
                    line['quantity'] * option['quantity'])
        calendar = self.env.ref('custom.timesheet_group1')
        delay = max_deadline and max_deadline.deadline or 0
        if m704:
            delay += M704_DELAY
        requested_date = calendar._get_date(
            start_date=fields.Date.context_today(self),
            delay=delay,
            resource_id=False)
        return {
            'date': requested_date.strftime('%Y-%m-%d'),
            'allowDeliverNow': allow_delivery_now,
            }

    def search(self, cr, uid, domain, offset=0, limit=None,
               order=None, context=None, count=False):
        if context is None:
            context = {}
        if context.get('my_company_order'):
            user = self.pool['res.users'].browse(cr, uid, uid)
            domain.append(['company_id', '=', user.company_id.id])
        # If we do not want to show explicitly the cancel sale order
        if 'show_cancel' in domain:
            domain = [('status', '=', 'cancel')]
        return super(SaleOrder, self).search(
            cr, uid, domain,
            offset=offset, limit=limit,
            order=order, context=context, count=count)

    @api.depends('warehouse_id.rla_id', 'partner_id')
    def _compute_rla(self):
        for record in self:
            if record.partner_id.kind == 'rla':
                record.rla_id = record.partner_id
            else:
                record.rla_id = record.warehouse_id.rla_id

    @api.model
    def create(self, vals):
        if vals.get('without_bon_confection'):
            if vals['without_bon_confection_payment'] == 'gratuit':
                vals['client_order_ref'] = 'SANS BON (imputation : gratuit)'
            else:
                vals['client_order_ref'] = 'SANS BON (imputation : point)'
        return super(SaleOrder, self).create(vals)

    @api.multi
    def write(self, vals):
        master_edit = False
        if self.user_has_groups('custom.group_custom_master_edit'):
            self = self.suspend_security()
            master_edit = True
        for sale in self:
            if (self._context.get('pos_delivery') and
                    'date_assigned' in vals and sale.date_assigned):
                # A date has been already set manually
                del vals[key]

            update_date = False
            for key in [
                    'date_order',
                    'requested_date',
                    'date_purchased',
                    'date_assigned']:
                if key in vals:
                    update_date = True

            if not master_edit and update_date and self.search([
                    ('holding_invoice_id', '!=', False),
                    ('id', 'in', self.ids)]):
                raise UserError(
                    u'La commande est facturée ou en cours de facturation '
                    u'Vous ne pouvez plus éditer les dates')
            if 'order_line' in vals and sale.status != 'draft':
                # this block is temporary there
                # while stock is out of range
                values = copy.deepcopy(vals)
                sale._log_message(values['order_line'])
            super(SaleOrder, sale).write(vals)
        return True

    @api.multi
    def _log_message(self, order_line):
        # temporary method
        self.ensure_one()
        new_vals = self._extract_wrote_sale_lines(order_line)
        infos = []
        stats = {'new': 0, 'upd': 0, 'new_opt': 0, 'upd_opt': 0}
        for sale in new_vals:
            line_id, values = sale.items()[0]
            if 'options' in values:
                for option in values['options']:
                    if option.get('id'):  # existing line
                        stats['upd_opt'] += 1
                    else:
                        stats['new_opt'] += 1
            if line_id:
                stats['upd'] += 1
            else:
                stats['new'] += 1
        infos.append(u'Modification après validation')
        if stats['new']:
            infos.append(u"Produits créées: %s" % stats['new'])
        if stats['upd']:
            infos.append(u"Produits mis à jour: %s" % stats['upd'])
        if stats['upd_opt']:
            infos.append(u"Opérations créées: %s" % stats['new_opt'])
        if stats['upd_opt']:
            infos.append(u"Opérations mise à jour: %s" % stats['upd_opt'])
        self.message_post(
            subject="Modifications vente",
            body='<pre>'+'\n'.join(infos)+'</pre>')

    @api.model
    def _extract_wrote_sale_lines(self, order_line):
        """
        Format du order_line du vals = [
            [4, 159085, False],  # no change to line
            [4, 159087, False],  # no change to line
            [1, 159086, {'optional_bom_line_ids': [
                # optional lines
                [0, False, {'bom_line_id': 4073, 'sale_line_id': 159086,
                            'qty': 1}],   # new option added
                [1, 198828, {'qty': 3}],  # modified qty only
                [4, 198829, False],  # no change to option
                ]}
            ]]
        """
        # temporary method donc on laisse comme ça
        new = []
        bom_line_ids = []
        for line in order_line:
            line_id = line[1]
            row = {line_id: {}}
            values = line[2]
            if values and 'optional_bom_line_ids' in values:
                options = values.pop('optional_bom_line_ids')
                opts = []
                for option in options:
                    if option[2]:
                        opts.append({
                            'bom_line_id': option[2].get('bom_line_id'),
                            'qty': option[2].get('qty'),
                            'id': option[1],
                        })
                        bom_line_ids.append(option[2].get('bom_line_id'))
                row[line_id].update({'options': opts})
            if values:
                row[line_id].update(values)
            if not row[line_id]:
                row = False
            if row:
                new.append(row)
        return new

    @api.model
    def _prepare_invoice(self, order, lines):
        res = super(SaleOrder, self)._prepare_invoice(order, lines)
        if order.section_id.journal_id:
            res['journal_id'] = order.section_id.journal_id.id
        elif self._context.get('force_company'):
            res['journal_id'] = self.env['account.journal'].search([
                ['type', '=', 'sale'],
                ['company_id', '=', self._context['force_company']],
                ]).id
        return res

    @api.multi
    def button_unblock_sale(self):
        self.ensure_one()
        exception_ids = self.detect_exceptions()
        if self.blocked and len(exception_ids) == 1:
            action = self.env.ref('custom.act_manual_unblock_sale_order')
            return action.read()[0]
        # TODO FIXME the detect_exception seem to not update the exception
        self.write({'exception_ids': [(6, 0, exception_ids)]})
        if exception_ids:
            action = self.env.ref('custom.act_still_error_sale_order')
            return action.read()[0]
        return True

    @api.multi
    def action_cancel(self):
        for sale in self:
            if sale.status == 'delivered':
                if sale.invoice_state in ('pending', 'invoiced'):
                    raise UserError(
                        u'La commande est déjà facturé ou en cours '
                        u'de facturation, elle ne peut pas être annulé')
            try:
                with sale._cr.savepoint():
                    super(SaleOrder, sale).action_cancel()
            except:
                sale.write({'force_cancel': True})
        return True

    @api.multi
    def uncancel(self):
        self.write({'force_cancel': False})
        return True

    @api.multi
    def action_send_quote_mindef(self):
        # Rend visible dans le portail les devis
        now = datetime.now().strftime(DEFAULT_SERVER_DATE_FORMAT)
        self.write({
            'date_quotation_proposed': now,
            'is_quotation': True
            })
        template = self.env.ref('custom.mindef_quote_email')
        if not self.rla_id:
            raise UserError(u'Vous devez renseigner le RLA sur votre antenne '
                            u' afin de proposer un devis')
        # Envoi un email aux personnes associé à la fct rla
        # et CESCOF
        cescof = self.env.ref('custom.cescof_customer')
        emails = [x.email for x in cescof.notify_partner_ids
                  if x.email]
        emails += [x.email for x in self.rla_id.notify_partner_ids
                   if x.email]
        if emails:
            vals = {'email_to': ','.join(emails)}
            template.write(vals)
            mail_id = template.send_mail(self.id)
            # Set mail to be send avoiding spamoo filter
            mail = self.env['mail.mail'].browse(mail_id)
            mail.write({'authorized': True})
        else:
            self.env['report'].get_pdf(
                self, template.report_template.report_name)
        if not self.rla_id.portal_partner_ids:
            raise UserError(
                u"Le RLA lié à la commande n'a pas de "
                u"'personnel ayant un accès au portail' de défini.\n"
                u"Veuillez le configurer correctement")
        return True

    @api.multi
    def get_tax_amount(self):
        # TODO make it readable
        tax_grouped = {}
        for order in self:
            for line in order.order_line:
                taxes = line.tax_id.compute_all(
                    (line.price_unit * (1 - (line.discount or 0.0) / 100.0)),
                    line.product_uom_qty, line.product_id,
                    order.partner_id)['taxes']
                for tax in taxes:
                    tax_obj = self.pool['account.tax'].browse(
                        self.env.cr, self.env.uid, tax['id'])
                    val = {
                        'name': tax['name'],
                        'description': tax_obj.description,
                        'amount': tax['amount'],
                    }
                    key = (tax['id'])
                    if key not in tax_grouped:
                        tax_grouped[key] = val
                    else:
                        tax_grouped[key]['amount'] += val['amount']
        return tax_grouped.values()

    @api.model
    def _check_abilis_exception(self, exception):
        """Generic funtion for exceptions on confirmed order"""
        return False

    @api.multi
    def print_quotation(self):
        self.ensure_one()
        self.signal_workflow('quotation_sent')
        return self.env['report'].get_action(
            self, 'custom_report.report_sale_custom')

    @api.multi
    def confirm_sale_from_pos(self):
        self.ensure_one()
        if self.is_quotation:
            return False
        return True

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False,
                        submenu=False):
        res = super(SaleOrder, self).fields_view_get(
            view_id=view_id, view_type=view_type, toolbar=toolbar,
            submenu=submenu)
        user = self.env['res.users'].browse(self._uid)
        company = user.company_id
        abilis_company = self.env.ref('base.main_company')
        report_sale_order = self.env.ref(
            'sale.report_sale_order')
        report_detailed_sale_order = self.env.ref(
            'custom_report.report_detailed_sale_order')
        print_submenu_ids = []
        if company == abilis_company:
            print_submenu_ids = print_submenu_ids + [
                report_sale_order.id,
                report_detailed_sale_order.id
            ]
        list_print_submenu_to_hide = []
        for print_submenu in res.get('toolbar', {}).get('print', []):
            if print_submenu['id'] in print_submenu_ids:
                list_print_submenu_to_hide.append(print_submenu)
        for print_submenu_to_hide in list_print_submenu_to_hide:
            res['toolbar']['print'].remove(print_submenu_to_hide)
        return res

    @api.multi
    def action_invoice_create(self, grouped=False, states=None,
                              date_invoice=False):
        invoice_id = super(SaleOrder, self).action_invoice_create(
            grouped=grouped,
            states=states,
            date_invoice=date_invoice)
        for invoice in self.env['account.invoice'].browse(invoice_id):
            client_order_ref_list = []
            for sale in invoice.sale_ids:
                if sale.client_order_ref:
                    client_order_ref_list.append(sale.client_order_ref)
            invoice.client_order_ref = ', '.join(client_order_ref_list)
        return invoice_id


class SaleOrderLineOption(models.Model):
    _inherit = 'sale.order.line.option'

    note = fields.Text()
    invalid_qty = fields.Boolean(
        compute='_compute_invalid_qty',
        store=True)

    @api.multi
    @api.depends('qty', 'bom_line_id.max_qty')
    def _compute_invalid_qty(self):
        for record in self:
            if record.qty > record.bom_line_id.max_qty:
                record.invalid_qty = True
            else:
                record.invalid_qty = False

    @api.multi
    @api.onchange('qty')
    def onchange_qty(self):
        for record in self:
            if self.bom_line_id and self.bom_line_id.max_qty < record.qty:
                return {'warning': {
                    'title': 'Erreur',
                    'message': 'La quantité maximal est %s'
                               % self.bom_line_id.max_qty}
                }

    @api.multi
    def update_operation(self):
        self.ensure_one()
        return {
            'name': u"Mise à jour opération",
            'res_model': 'sale.order.update.bom.line',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'view_id': self.env.ref(
                'custom.view_sale_order_update_bom_line_form').id,
            'view_mode': 'form',
        }
