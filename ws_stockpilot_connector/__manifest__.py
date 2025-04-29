# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
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
        "stock",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/stockpilot_configuration_views.xml",
    ],
    "installable": True,
    "application": True,
}
