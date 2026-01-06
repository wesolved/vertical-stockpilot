# Copyright (C) 2026 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Stockpilot Connector - Shipping Method Mapping",
    "version": "18.0.1.0.0",
    "summary": "Map Stockpilot shipping lines to Odoo delivery carriers",
    "author": "WeSolved B.V.",
    "website": "https://wesolved.com",
    "category": "Stock",
    "license": "LGPL-3",
    "depends": [
        "ws_stockpilot_connector",
        "delivery",
    ],
    "data": [
        "views/stockpilot_configuration_views.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": True,
}
