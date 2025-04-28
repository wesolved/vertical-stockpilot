
{
    'name': 'Stockpilot Connector',
    'version': '16.0.1.0.0',
    'summary': 'Connector for Stockpilot integration',
    'author': 'WeSolved',
    'website': 'https://wesolved.com',
    'category': 'Stock',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'stock',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/stockpilot_menus.xml',
        'views/stockpilot_configuration_views.xml',
    ],
    'installable': True,
    'application': True,
}
