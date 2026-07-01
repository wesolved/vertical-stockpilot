# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Stockpilot Connector",
    "version": "19.0.1.3.0",
    "summary": "Connector for Stockpilot integration",
    "author": "WeSolved B.V.",
    "website": "https://wesolved.com",
    "category": "Stock",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "sale_stock",
        "queue_job",
    ],
    "data": [
        "data/ir_cron.xml",
        "data/product_pricelist.xml",
        "security/ir.model.access.csv",
        "views/stockpilot_configuration_views.xml",
        "views/product_template_views.xml",
        "views/product_product_views.xml",
        "views/sale_order_views.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
}
