# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class StockpilotConfiguration(models.Model):
    _inherit = "stockpilot.configuration"
    _description = "Stockpilot Configuration"

    country_warehouse_ids = fields.One2many(
        "country.warehouse", "stockpilot_configuration_id", string="Country Warehouses"
    )
