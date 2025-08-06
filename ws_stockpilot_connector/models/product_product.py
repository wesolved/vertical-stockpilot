# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    stockpilot_ids = fields.One2many(
        "stockpilot.product.product", "product_product_id", copy=False
    )

    def _update_stockpilot_stock(self):
        """
        Trigger an inventory update towards Stockpilot for
        all linked stockpilot.product.product records.
        Sends the current quantity for each variant to Stockpilot.
        """
        for product in self.stockpilot_ids:
            connection = product.stockpilot_configuration_id._get_connection()
            product_data = {
                "id": product.stockpilot_id,
                "quantity": product.product_product_id.qty_available,
            }
            connection._execute_post_request("inventory/update", product_data)


class StockPilotProductProduct(models.Model):
    _name = "stockpilot.product.product"

    stockpilot_configuration_id = fields.Many2one("stockpilot.configuration")
    product_product_id = fields.Many2one("product.product")
    stockpilot_id = fields.Char(string="Stockpilot Product ID", copy=False)

    def create(self, vals):
        """
        Override create to also create the variant in Stockpilot asynchronously.

        Args:
            vals (dict): Values for the new record.
        Returns:
            recordset: Created record(s).
        """
        res = super().create(vals)
        res.with_delay()._push_stockpilot_variant()
        return res

    def _push_stockpilot_variant(self):
        """
        Create this product variant in Stockpilot via API if not already present.
        Ensures a Stockpilot product template exists and then creates
        the variant (inventory item).
        Updates the stockpilot_id field with the returned item ID from Stockpilot.
        """
        spt = self.product_product_id.product_tmpl_id.stockpilot_ids.filtered(
            lambda sp: sp.stockpilot_configuration_id
            == self.stockpilot_configuration_id
        )
        if not spt:
            spt = (
                self.env["stockpilot.product.template"]
                .with_context({"skip_delay": True})
                .create(
                    {
                        "product_tmpl_id": self.product_product_id.product_tmpl_id.id,
                        "stockpilot_configuration_id": self.stockpilot_configuration_id.id,
                    }
                )
            )

        product_data = {
            "item_name": self.product_product_id.name,
            "product_id": spt.stockpilot_id,  # Get this from stockpilot product template
            "sku": self.product_product_id.default_code or self.product_product_id.name,
            "barcode": self.product_product_id.barcode
            or str(self.product_product_id.id),
            "condition": "NEW",
            "loc": "NVT",
        }
        connection = self.stockpilot_configuration_id._get_connection()
        response = connection._execute_post_request("inventory/create", product_data)
        self.stockpilot_id = response.get("item_id")
