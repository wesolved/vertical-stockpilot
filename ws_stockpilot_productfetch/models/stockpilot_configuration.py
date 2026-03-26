# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class StockpilotConfiguration(models.Model):
    _inherit = "stockpilot.configuration"

    def action_fetch_products(self):
        """Open wizard to fetch products from Stockpilot"""
        self.ensure_one()
        
        return {
            "type": "ir.actions.act_window",
            "name": "Fetch Products",
            "res_model": "product.fetch.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_configuration_id": self.id,
            },
        }
