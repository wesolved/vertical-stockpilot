# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


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
        brand_id = None
        if not self.product_tmpl_id.product_brand_id:
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
            "brand": brand_id.stockpilot_id if brand_id else None,
            "category": category_id.stockpilot_id if category_id else None,
        }
        connection = self.stockpilot_configuration_id._get_connection()
        response = connection._execute_post_request("products/create", product_data)
        self.stockpilot_id = response.get("product_id")

    def _push_image(self):
        """
        Push the product image to Stockpilot if it exists.
        """
        if self.product_tmpl_id.image_1920 and self.stockpilot_id:
            image_data = {
                "image_file": self.product_tmpl_id.image_1920.decode("utf-8"),
            }
            connection = self.stockpilot_configuration_id._get_connection()
            connection._execute_post_request(f"products/{self.stockpilot_id}/set-image", image_data)

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
