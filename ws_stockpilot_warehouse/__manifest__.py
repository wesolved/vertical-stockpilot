# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    "name": "Stockpilot Connector - Warehouse Selection",
    "version": "17.0.1.0.0",
    "summary": "Map countries with specific warehouses for Stockpilot orders",
    "author": "WeSolved B.V.",
    "website": "https://wesolved.com",
    "category": "Stock",
    "license": "LGPL-3",
    "depends": [
        "ws_stockpilot_connector",
    ],
    "data": [
        "views/stockpilot_configuration_views.xml",
        "security/ir_model_access.csv",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
}
