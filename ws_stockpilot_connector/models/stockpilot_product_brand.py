# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockPilotProductBrand(models.Model):
    _name = "stockpilot.product.brand"

    stockpilot_channel_id = fields.Many2one("stockpilot.channel")
    brand_id = fields.Many2one("product.brand")
    stockpilot_configuration_id = fields.Many2one("stockpilot.configuration")
    stockpilot_id = fields.Char(string="Stockpilot Product ID", copy=False)

    def _create_stockpilot_brand(self):
        """
        Execute an API call to Stockpilot to create a brand for this record.
        Updates the stockpilot_id field with the returned ID from Stockpilot.
        """
        product_data = {
            "name": self.brand_id.name,
        }
        connection = self.stockpilot_configuration_id._get_connection()
        response = connection._execute_post_request("brands/create", product_data)
        self.stockpilot_id = response.get("id")

    def create(self, vals):
        """
        Override create to also create the brand in Stockpilot
        (asynchronously unless 'skip_delay' is set in context).

        Args:
            vals (dict): Values for the new record.
        Returns:
            recordset: Created record(s).
        """
        res = super().create(vals)
        if self.env.context.get("skip_delay"):
            res._create_stockpilot_brand()
        else:
            res.with_delay()._create_stockpilot_brand()
        return res
