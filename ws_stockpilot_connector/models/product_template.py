# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


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


class StockPilotProductTemplate(models.Model):
    _name = "stockpilot.product.template"

    product_tmpl_id = fields.Many2one("product.template")
    stockpilot_configuration_id = fields.Many2one("stockpilot.configuration")
    stockpilot_id = fields.Char(string="Stockpilot Product ID", copy=False)

    def _push_stockpilot_inventory(self):
        """
        Execute an API call to Stockpilot to create this product template.
        Raises a UserError if no brand is defined on the product.
        Updates the stockpilot_id field with the returned product ID from Stockpilot.
        """
        if not self.product_tmpl_id.product_brand_id:
            raise UserError(_("No brand defined on the product"))

        brand_id = self.product_tmpl_id.product_brand_id.with_context(
            {"skip_delay": True}
        )._get_or_create_stockpilot_brand(self.stockpilot_configuration_id)
        category_id = self.product_tmpl_id.categ_id.with_context(
            {"skip_delay": True}
        )._get_or_create_stockpilot_category(self.stockpilot_configuration_id)

        product_data = {
            "title": self.product_tmpl_id.name,
            "description": self.product_tmpl_id.description
            or self.product_tmpl_id.name,
            "is_active": self.product_tmpl_id.active,
            "brand": brand_id.stockpilot_id,
            "category": category_id.stockpilot_id,
        }
        connection = self.stockpilot_configuration_id._get_connection()
        response = connection._execute_post_request("products/create", product_data)
        self.stockpilot_id = response.get("product_id")

    def create(self, vals):
        """
        Override create to also create the product in Stockpilot
        (asynchronously unless 'skip_delay' is set in context).

        Args:
            vals (dict): Values for the new record.
        Returns:
            recordset: Created record(s).
        """
        res = super().create(vals)
        if self.env.context.get("skip_delay"):
            res._push_stockpilot_inventory()
        else:
            res.with_delay()._push_stockpilot_inventory()
        return res
