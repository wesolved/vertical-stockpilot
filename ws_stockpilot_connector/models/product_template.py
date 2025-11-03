# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    stockpilot_ids = fields.One2many(
        "stockpilot.product.template", "product_tmpl_id", copy=False
    )

    def _create_stockpilot_product(self):
        """
        Schedule the creation of Stockpilot products for each product template in the recordset.
        """
        for product in self:
            product.with_delay()._push_stockpilot_product()
