# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    stockpilot_ids = fields.One2many(
        "stockpilot.product.category", "category_id", copy=False
    )

    def _get_or_create_stockpilot_category(self, config_id):
        """Create category on stock pilot."""
        self.ensure_one()
        res = self.stockpilot_ids.filtered(
            lambda cat: cat.stockpilot_configuration_id == config_id
        )
        if not res:
            res = self.env["stockpilot.product.category"].create(
                {"stockpilot_configuration_id": config_id.id, "category_id": self.id}
            )
        return res
