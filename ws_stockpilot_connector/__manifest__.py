# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# @author Insaf Amrani <insaf.amrani.boukhobza@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Stockpilot Connector",
    "version": "16.0.1.0.0",
    "summary": "Connector for Stockpilot integration",
    "author": "WeSolved",
    "website": "https://wesolved.com",
    "category": "Stock",
    "license": "LGPL-3",
    "depends": [
        "base",
        "sale_stock",
        "queue_job",
        "queue_job_batch",
    ],
    "data": [
        "data/cron.xml",
        "security/group.xml",
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/stockpilot_configuration_views.xml",
        "views/product_template_views.xml",
        "views/product_product_views.xml",
        "views/sale_order_views.xml",
        "views/stockpilot_batch_export_views.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
}
