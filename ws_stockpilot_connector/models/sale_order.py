# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import datetime
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    stockpilot_id = fields.Integer(copy=False)
    stockpilot_configuration_id = fields.Many2one(
        "stockpilot.configuration", readonly=True
    )
    stockpilot_error = fields.Boolean(string="Data mismatch", copy=False)

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
                {"register_order_id": str(self.id), "source": "api"},
            )
            _logger.info(res)

    def _get_warehouse(self, stockpilot_configuration_id, country_code):
        return stockpilot_configuration_id.default_warehouse_id

    def _stockpilot_fulfill(self, t_and_t):
        """
        Trigger a fulfill update for this order in Stockpilot.
        """
        if self.stockpilot_configuration_id:
            if not t_and_t:
                t_and_t = (
                    self.env["stock.picking"]
                    .search(
                        [
                            ("origin", "=", self.name),
                            ("carrier_tracking_ref", "!=", False),
                        ],
                        limit=1,
                    )
                    .carrier_tracking_ref
                )
            connection = self.stockpilot_configuration_id._get_connection()
            res = connection._execute_post_request(
                "orders/fulfil",
                {
                    "order_pk": self.stockpilot_id,
                    "tracking_code": t_and_t or "",
                    "carrier_name": self.stockpilot_configuration_id.carrier_method,
                    "carrier_code": self.stockpilot_configuration_id.carrier_method
                },
            )
            _logger.info(
                "============================================================="
            )
            _logger.info(res)

    def override_order(self, order, order_info):
        """
        Placeholder method for custom order overrides.
        Can be extended in other modules to modify the order after creation.

        Args:
            order (recordset): The created sale.order record.

        Returns:
            recordset: The potentially modified sale.order record.
        """
        return order

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
        order_number = order.get("channel_order_number") or order.get("order_number")
        order_date = order.get("created_at")
        order_info = order
        if self.search([("stockpilot_id", "=", order_id)]):
            _logger.debug(f"Stockpilot order {order_id} already exists")
            return

        order = order.get("order_details")

        def _sp_val(key, default=""):
            val = order.get(key, default)
            return default if val is None else val

        company_id = False
        if order.get("shipment_company"):
            # First check for parent
            partner = {
                "name": _sp_val("shipment_company"),
                "street": "%s %s %s"
                % (
                    _sp_val("shipment_street"),
                    _sp_val("shipment_housenumber"),
                    _sp_val("shipment_suffix"),
                ),
                "zip": _sp_val("shipment_zipcode"),
                "city": _sp_val("shipment_city"),
                "country": _sp_val("shipment_country"),
                "email": _sp_val("customer_email"),
                "phone": _sp_val("customer_phone"),
            }
            company_id = self.env["res.partner"]._get_stockpilot_partner(partner)

        partner = {
            "name": "%s %s"
            % (_sp_val("shipment_firstname"), _sp_val("shipment_lastname")),
            "street": "%s %s %s"
            % (
                _sp_val("shipment_street"),
                _sp_val("shipment_housenumber"),
                _sp_val("shipment_suffix"),
            ),
            "zip": _sp_val("shipment_zipcode"),
            "city": _sp_val("shipment_city"),
            "country": _sp_val("shipment_country"),
            "email": _sp_val("customer_email"),
            "phone": _sp_val("customer_phone"),
        }
        partner_id = self.env["res.partner"]._get_stockpilot_partner(partner)
        if company_id and partner_id != company_id:
            partner_id.parent_id = company_id.id

        billing_partner = {
            "name": "%s %s"
            % (_sp_val("billing_firstname"), _sp_val("billing_lastname")),
            "street": "%s %s %s"
            % (
                _sp_val("billing_street"),
                _sp_val("billing_housenumber"),
                _sp_val("billing_suffix"),
            ),
            "zip": _sp_val("billing_zipcode"),
            "city": _sp_val("billing_city"),
            "country": _sp_val("billing_country"),
            "email": _sp_val("customer_email"),
            "phone": _sp_val("customer_phone"),
        }

        if partner != billing_partner:
            if company_id:
                parent_id = company_id
            else:
                parent_id = partner_id
            billing_partner = self.env["res.partner"]._get_stockpilot_partner(
                billing_partner, parent_id
            )
        else:
            billing_partner = partner_id

        order_id = self.env["sale.order"].create(
            {
                "name": order_number,
                "partner_id": partner_id.id,
                "partner_shipping_id": partner_id.id,
                "partner_invoice_id": billing_partner.id,
                "client_order_ref": order_number,
                "team_id": stockpilot_configuration_id.crm_team_id.id,
                "date_order": datetime.datetime.fromisoformat(order_date).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "stockpilot_id": order_id,
                "stockpilot_configuration_id": stockpilot_configuration_id.id,
                "warehouse_id": self._get_warehouse(
                    stockpilot_configuration_id, order.get("shipment_country")
                ).id,
                "currency_id": self.env['res.currency'].search([("name", "=", order.get("currency_code"))], limit=1).id,
            }
        )
        order_id = self.override_order(order_id, order_info)

        missing_product = False
        for line in order.get("line_items"):
            _logger.info(line)
            product = self.env["stockpilot.product.product"].search(
                [("stockpilot_id", "=", line.get("product_id"))]
            )
            if not product or not line.get("product_id"):
                missing_product = True
                continue
            self.env["sale.order.line"].create(
                {
                    "order_id": order_id.id,
                    "stockpilot_id": line.get("id"),
                    "name": (
                        line.get("sales_channel_title")
                        if line.get("sales_channel_title")
                        else product.product_product_id[0].name
                    ),
                    "product_id": product.product_product_id[0].id,
                    "product_uom_qty": line.get("quantity"),
                    "price_unit": float(line.get("retail_price"))
                    / (100 + float(line.get("vat_rate")))
                    * 100,
                }
            )
        _logger.info(order.get("shipping_total"))
        if order.get("shipping_total"):
            self.env["sale.order.line"].create(
                {
                    "order_id": order_id.id,
                    "name": "Shipping",
                    "price_unit": float(order.get("shipping_total", 0))
                    / (100 + float(order.get("vat_rate", 0)))
                    * 100,
                    "product_id": stockpilot_configuration_id.shipping_product.id,
                    "product_uom_qty": 1,
                }
            )
        if order.get("discount"):
            tax = self.env["account.tax"].search(
                [("name", "=", order.get("vat_rate"))], limit=1
            )
            self.env["sale.order.line"].create(
                {
                    "order_id": order_id.id,
                    "name": "Discount",
                    "price_unit": (
                        float(order.get("discount", 0))
                        / (100 + float(order.get("vat_rate", 0)))
                    )
                    * -1
                    * 100,
                    "product_id": stockpilot_configuration_id.discount_product.id,
                    "product_uom_qty": 1,
                    "tax_id": [(6, 0, tax.ids)] if tax else [(5, 0, 0)],
                }
            )
        order_id.message_post(body=_("Customer note: %s") % order.get("customer_note"))
        stockpilot_configuration_id._get_connection()
        if missing_product:
            order_id.message_post(
                body=_(
                    "One or more products in this order could not be found in Odoo and have been skipped. Please check this order yourself."
                )
            )
            order_id.stockpilot_error = True

        if stockpilot_configuration_id.auto_confirm_orders and not missing_product:
            order_id.action_confirm()
        order_id.with_delay()._stockpilot_forwarding()
