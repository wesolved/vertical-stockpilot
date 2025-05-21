# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import logging
from datetime import datetime

import requests
from odoo import fields, models

_logger = logging.getLogger(__name__)


class StockpilotSync(models.Model):
    _name = "stockpilot.sync"
    _description = "Stockpilot Synchronization"

    def _get_stockpilot_orders(self, config, last_sync_date=None):
        """Fetch orders from Stockpilot API with proper error handling"""
        try:
            url = f"{config.base_url.rstrip('/')}/orders"
            headers = {
                "X-CLIENT-ID": config.api_client_id,
                "X-CLIENT-SECRET": config.api_client_secret,
            }
            params = {
                "page": 1,
                "page_size": 50,
                "modified_since": (
                    last_sync_date.isoformat() if last_sync_date else None
                ),
            }

            _logger.info(f"Fetching orders from {url}")
            response = requests.get(url, headers=headers, params=params, timeout=15)

            # Add detailed response logging
            _logger.debug(f"API response status: {response.status_code}")
            _logger.debug(f"API response content: {response.text}")

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                _logger.error(f"Unexpected API response format: {data}")
                return None

            if "results" not in data:
                _logger.error(f"API response missing 'results' key: {data}")
                return None

            return data

        except requests.exceptions.RequestException as e:
            _logger.error(f"Request failed: {str(e)}")
            return None
        except ValueError as e:
            _logger.error(f"Invalid JSON response: {str(e)}")
            return None
        except Exception as e:
            _logger.error(f"Unexpected error: {str(e)}")
            return None

    def _fetch_stockpilot_orders(self):
        """Fetch orders from Stockpilot with the actual API structure"""
        _logger.info("Starting Stockpilot order import")

        configs = self.env["stockpilot.configuration"].search([])
        if not configs:
            _logger.error("No Stockpilot configurations found")
            return False

        for config in configs:
            try:
                _logger.info(f"Processing config for company: {config.company_id.name}")

                # Get orders from API
                orders = self._get_stockpilot_orders(config)
                if not orders or not orders.get("results"):
                    _logger.warning("No orders received from Stockpilot API")
                    continue

                order_list = orders.get("results", [])
                _logger.info(f"Received {len(order_list)} orders from Stockpilot")

                success_count = 0
                for order_data in order_list:
                    try:
                        if self._process_stockpilot_order(
                            order_data, config.company_id
                        ):
                            success_count += 1
                    except Exception as e:
                        _logger.error(
                            f"Failed {order_data.get('order_number')}: {str(e)}"
                        )

                _logger.info(
                    f"Successfully imported {success_count}/{len(order_list)} orders"
                )
                config.last_sync_date = datetime.now()

            except Exception as e:
                _logger.error(f"Error processing config {config.id}: {str(e)}")
                continue

        return True

    def _process_stockpilot_order(self, order_data, company):
        """Process a single Stockpilot order with fixed datetime handling"""
        _logger.info(f"Processing order {order_data.get('order_number')}")

        try:
            # Find or create partner
            partner = self._find_or_create_customer(order_data, company)
            if not partner:
                _logger.error(
                    f"Failed to find/create customer for order {order_data.get('order_number')}"
                )
                return False

            # Handle datetime conversion
            if order_data.get("order_placed_dt"):
                try:
                    order_date = datetime.strptime(
                        order_data.get("order_placed_dt"), "%Y-%m-%dT%H:%M:%S%z"
                    )
                    # Convert to naive datetime
                    order_date = order_date.replace(tzinfo=None)
                except ValueError as e:
                    _logger.warning(
                        f"Invalid date format, using current date: {str(e)}"
                    )
                    order_date = fields.Datetime.now()
            else:
                order_date = fields.Datetime.now()

            # Prepare order values
            order_vals = {
                "stockpilot_order_id": order_data.get("id"),
                "client_order_ref": order_data.get("order_number"),
                "partner_id": partner.id,
                "date_order": order_date,
                "company_id": company.id,
                "order_line": self._prepare_order_lines(
                    order_data.get("order_details", {}).get("line_items", [])
                ),
                "note": f"Imported {order_data.get('handle', 'Unknown')}",
            }

            # Check if order exists
            existing_order = self.env["sale.order"].search(
                [
                    ("stockpilot_order_id", "=", order_data.get("id")),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )

            if existing_order:
                _logger.info(f"Updating existing order {existing_order.name}")
                existing_order.write(order_vals)
                order = existing_order
            else:
                _logger.info(f"Creating new order for {order_data.get('order_number')}")
                order = self.env["sale.order"].create(order_vals)

            # Add shipping line if needed
            shipping_total = float(
                order_data.get("order_details", {}).get("shipping_total", 0)
            )
            if shipping_total > 0:
                self._add_shipping_line(order, shipping_total)

            if order.state == "draft":
                order.action_confirm()
                _logger.info(f"Confirmed order {order.name}")

            return True

        except Exception as e:
            _logger.error(
                f"Failed to process order {order_data.get('order_number')}: {str(e)}",
                exc_info=True,
            )
            return False

    def _find_or_create_customer(self, order_data, company):
        """Find or create partner from Stockpilot order data"""
        try:
            order_details = order_data.get("order_details", {})
            email = order_details.get("customer_email")
            phone = order_details.get("customer_phone")
            name = order_data.get("customer_name", "Stockpilot Customer")

            if email:
                partner = self.env["res.partner"].search(
                    [("email", "=", email), ("company_id", "=", company.id)], limit=1
                )
                if partner:
                    return partner

            if name and phone:
                partner = self.env["res.partner"].search(
                    [
                        ("name", "=", name),
                        ("phone", "=", phone),
                        ("company_id", "=", company.id),
                    ],
                    limit=1,
                )
                if partner:
                    return partner

            _logger.info(f"Creating new partner for {name}")
            partner_vals = {
                "name": name,
                "email": email,
                "phone": phone,
                "company_id": company.id,
                "customer_rank": 1,
                "type": "invoice",
            }

            if order_details.get("billing_street"):
                partner_vals.update(
                    {
                        "street": (
                            f"{order_details.get('billing_street')} "
                            f"{order_details.get('billing_housenumber', '')}"
                        ),
                        "street2": order_details.get("billing_address_2", ""),
                        "city": order_details.get("billing_city", ""),
                        "zip": order_details.get("billing_zipcode", ""),
                        "country_id": self.env["res.country"]
                        .search(
                            [("code", "=", order_details.get("billing_country"))],
                            limit=1,
                        )
                        .id,
                    }
                )

            return self.env["res.partner"].create(partner_vals)

        except Exception as e:
            _logger.error(f"Failed to find/create customer: {str(e)}")
            return False

    def _create_order_from_stockpilot(self, order_data, company):
        """Create new Odoo order from Stockpilot data"""
        partner = self._find_or_create_customer(order_data["customer"], company)

        order_vals = {
            "stockpilot_order_id": order_data["id"],
            "partner_id": partner.id,
            "date_order": order_data.get("date", fields.Datetime.now()),
            "state": self._map_stockpilot_to_odoo_status(
                order_data.get("status", "New")
            ),
            "company_id": company.id,
            "order_line": self._prepare_order_lines(order_data.get("lines", [])),
        }

        return self.env["sale.order"].create(order_vals)

    def _update_order_from_stockpilot(self, order, order_data):
        """Update existing Odoo order from Stockpilot data"""
        update_vals = {
            "state": self._map_stockpilot_to_odoo_status(
                order_data.get("status", order.state)
            ),
        }

        if "lines" in order_data:
            self._update_order_lines(order, order_data["lines"])

        order.write(update_vals)

    def _prepare_order_lines(self, line_items):
        """Prepare order line values from Stockpilot line items"""
        order_lines = []

        for line in line_items:
            try:
                if not line.get("sales_channel_title"):
                    _logger.warning("Line missing product title, skipping")
                    continue

                product = self.env["product.product"].search(
                    [
                        (
                            "name",
                            "=ilike",
                            line["sales_channel_title"].split("-")[0].strip(),
                        )
                    ],
                    limit=1,
                )

                if not product:
                    _logger.warning(
                        f"Product not found for: {line['sales_channel_title']}"
                    )
                    product = self._create_placeholder_product(
                        line["sales_channel_title"]
                    )

                price = float(line.get("retail_price", 0)) or float(
                    line.get("total_price", 0)
                )
                if price <= 0:
                    price = product.list_price

                order_lines.append(
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": float(line.get("quantity", 1)),
                            "price_unit": price,
                            "name": line["sales_channel_title"],
                        },
                    )
                )

            except Exception as e:
                _logger.error(f"Failed to process line: {str(e)}")
                continue

        _logger.info(f"Prepared {len(order_lines)} order lines")
        return order_lines

    def _create_placeholder_product(self, product_name):
        """Create a placeholder product when the real one isn't found"""
        try:
            _logger.info(f"Creating placeholder product for {product_name}")
            return self.env["product.product"].create(
                {
                    "name": product_name,
                    "type": "product",
                    "list_price": 0.0,
                    "standard_price": 0.0,
                }
            )
        except Exception as e:
            _logger.error(f"Failed to create placeholder product: {str(e)}")
            raise

    def _update_order_lines(self, order, lines_data):
        """Update existing order lines from Stockpilot data"""

    def _add_shipping_line(self, order, shipping_total):
        """Add shipping line to the order"""
        try:
            shipping_product = self.env["product.product"].search(
                [("name", "ilike", "shipping"), ("type", "=", "service")], limit=1
            )

            if not shipping_product:
                shipping_product = self.env["product.product"].create(
                    {
                        "name": "Shipping",
                        "type": "service",
                        "list_price": 0.0,
                        "invoice_policy": "order",
                    }
                )

            order.write(
                {
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "product_id": shipping_product.id,
                                "name": "Shipping Costs",
                                "product_uom_qty": 1,
                                "price_unit": shipping_total,
                                "is_delivery": True,
                            },
                        )
                    ]
                }
            )
        except Exception as e:
            _logger.error(f"Failed to add shipping line: {str(e)}")
