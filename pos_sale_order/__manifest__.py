# -*- coding: utf-8 -*-
# Copyright <2016> Akretion
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'POS To Sale Order',
    'version': '10.0.1.0.0',
    'category': 'Point Of Sale',
    'author': 'Akretion, Odoo Community Association (OCA)',
    'website': 'http://www.akretion.com',
    'license': 'AGPL-3',
    'depends': ['sale',
                'point_of_sale',
                #'sale_quick_payment',
               # 'account_bank_statement_sale_order',
                ],
    'data': ['views/sale_view.xml',
             'views/point_of_sale_view.xml',
             'data/res_partner_data.xml',
             'data/pos_config_data.xml',
             ],
    'demo': [],
    'installable': True,
}
