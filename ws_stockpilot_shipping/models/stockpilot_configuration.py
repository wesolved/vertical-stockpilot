# Copyright (C) 2026 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockpilotConfiguration(models.Model):
    _inherit = "stockpilot.configuration"

    shipping_method_ids = fields.One2many(
        "stockpilot.shipping.method",
        "stockpilot_configuration_id",
        string="Shipping Methods",
    )
