# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Stockpilot Product Fetch",
    "version": "19.0.1.0.0",
    "summary": "Fetch products from Stockpilot API",
    "author": "WeSolved B.V.",
    "website": "https://wesolved.com",
    "category": "Stock",
    "license": "LGPL-3",
    "depends": [
        "ws_stockpilot_connector",
        "product",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizard/product_fetch_wizard_views.xml",
        "views/stockpilot_configuration_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
