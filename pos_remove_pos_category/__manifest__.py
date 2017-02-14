# -*- coding: utf-8 -*-
#    autor Akretion (<http://www.akretion.com>
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html

{
    'name': 'POS Remove POS Category',
    'version': '10.0.0.1.0',
    'author': 'Akretion, Odoo Community Association (OCA)',
    'category': 'Sales Management',
    'depends': [
        'point_of_sale',
    ],
    'demo': [],
    'website': 'https://www.akretion.com',
    'data': [
        'point_of_sale_view.xml',
        'views/pos_category.xml',
    ],
    'installable': False,
}
