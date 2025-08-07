# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import datetime
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    stockpilot_id = fields.Integer()
    stockpilot_configuration_id = fields.Many2one(
        "stockpilot.configuration", readonly=True
    )

    _sql_constraints = [
        (
            "stockpilot_id_uniq",
            "unique(stockpilot_id)",
            "Stockpilot Order ID must be unique",
        )
    ]

    def _stockpilot_forwarding(self):
        """
        Trigger a forwarding update for this order in Stockpilot.
        Calls the Stockpilot API to update forwarding status for the order.
        """
        if self.stockpilot_configuration_id:
            connection = self.stockpilot_configuration_id._get_connection()
            res = connection._execute_patch_request(
                f"orders/{self.stockpilot_id}/update-forwarding",
                {"register_order_id": self.id, "source": "api"},
            )
            _logger.debug(res)

    def _stockpilot_fulfill(self, t_and_t):
        """
        Trigger a fulfill update for this order in Stockpilot.
        """
        if self.stockpilot_configuration_id:
            connection = self.stockpilot_configuration_id._get_connection()
            res = connection._execute_post_request(
                "orders/fulfil",
                {"order_pk": self.stockpilot_id, "tracking_code": t_and_t or ""},
            )
            _logger.debug(res)

    def _import_stockpilot_order(self, order, stockpilot_configuration_id):
        """
        Create a sale.order from a Stockpilot order payload.

        Args:
            order (dict): Stockpilot order data (API response structure).
            stockpilot_configuration_id (recordset): The configuration used for the import.

        Returns:
            None
        """
        order_id = order.get("id")
        order_number = order.get("order_number")
        order_date = order.get("created_at")
        if self.search([("stockpilot_id", "=", order_id)]):
            _logger.debug(f"Stockpilot order {order_id} already exists")
            return

        order = order.get("order_details")
        company_id = False
        if order.get("shipment_company"):
            # First check for parent
            partner = {
                "name": order.get("shipment_company"),
                "street": "%s %s %s"
                % (
                    order.get("shipment_street"),
                    order.get("shipment_housenumber"),
                    order.get("shipment_suffix"),
                ),
                "zip": order.get("shipment_zipcode"),
                "city": order.get("shipment_city"),
                "country": order.get("shipment_country"),
                "email": order.get("customer_email"),
                "phone": order.get("customer_phone"),
            }
            company_id = self.env["res.partner"]._get_stockpilot_partner(partner)

        partner = {
            "name": "%s %s"
            % (order.get("shipment_firstname"), order.get("shipment_lastname")),
            "street": "%s %s %s"
            % (
                order.get("shipment_street"),
                order.get("shipment_housenumber"),
                order.get("shipment_suffix"),
            ),
            "zip": order.get("shipment_zipcode"),
            "city": order.get("shipment_city"),
            "country": order.get("shipment_country"),
            "email": order.get("customer_email"),
            "phone": order.get("customer_phone"),
        }
        partner_id = self.env["res.partner"]._get_stockpilot_partner(partner)
        if company_id:
            partner_id.parent_id = company_id.id

        billing_partner = {
            "name": "%s %s"
            % (order.get("billing_firstname"), order.get("billing_lastname")),
            "street": "%s %s %s"
            % (
                order.get("billing_street"),
                order.get("billing_housenumber"),
                order.get("billing_suffix"),
            ),
            "zip": order.get("billing_zipcode"),
            "city": order.get("billing_city"),
            "country": order.get("billing_country"),
            "email": order.get("customer_email"),
            "phone": order.get("customer_phone"),
        }

        if partner != billing_partner:
            if company_id:
                parent_id = company_id
            else:
                parent_id = partner_id
            self.env["res.partner"]._get_stockpilot_partner(billing_partner, parent_id)

        order_id = self.env["sale.order"].create(
            {
                "name": order_number,
                "partner_id": partner_id.id,
                "date_order": datetime.datetime.fromisoformat(order_date).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "stockpilot_id": order_id,
                "stockpilot_configuration_id": stockpilot_configuration_id.id,
            }
        )
        for line in order.get("line_items"):
            product = self.env["stockpilot.product.product"].search(
                [("stockpilot_id", "=", line.get("product_id"))]
            )
            if not product:
                raise UserError(
                    _("Product %s does not exist" % line.get("sales_channel_title"))
                )
            self.env["sale.order.line"].create(
                {
                    "order_id": order_id.id,
                    "stockpilot_id": line.get("id"),
                    "name": line.get("sales_channel_title"),
                    "product_id": product.product_product_id.id,
                    "product_uom_qty": line.get("quantity"),
                    "price_unit": line.get("retail_price"),
                }
            )
        connection = stockpilot_configuration_id._get_connection()
        response = connection._execute_patch_request(
            f"orders/{order_id.stockpilot_id}/update-status", {"status": "pending"}
        )
        _logger.debug(response)
        order_id.action_confirm()
        self._stockpilot_forwarding()
