# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProductBrand(models.Model):
    _inherit = "product.brand"

    stockpilot_ids = fields.One2many("stockpilot.product.brand", "brand_id", copy=False)

    def _get_or_create_stockpilot_brand(self, config_id):
        """Create stockpilot brand"""
        if not self:
            return False
        self.ensure_one()
        res = self.stockpilot_ids.filtered(
            lambda brand: brand.stockpilot_configuration_id == config_id
        )
        if not res:
            res = self.env["stockpilot.product.brand"].create(
                {"stockpilot_configuration_id": config_id.id, "brand_id": self.id}
            )
        return res
