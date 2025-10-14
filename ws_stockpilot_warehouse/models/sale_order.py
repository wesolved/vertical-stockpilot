from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def get_warehouse(self, stockpilot_configuration_id, country_code):
        """
        Get the warehouse based on the country code using the CountryWarehouse mapping.
        If no specific mapping exists, return the default warehouse from the configuration.
        """
        warehouse_id = (
            self.env["country.warehouse"]
            .search(
                [
                    (
                        "stockpilot_configuration_id",
                        "=",
                        stockpilot_configuration_id.id,
                    ),
                    ("country_id.code", "=", country_code),
                ],
                limit=1,
            )
            .warehouse_id
        )
        if not warehouse_id:
            warehouse_id = stockpilot_configuration_id.default_warehouse_id

        return warehouse_id
