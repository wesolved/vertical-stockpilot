import logging

import requests
from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockpilotInventory(models.Model):
    _name = "stockpilot.inventory"
    _description = "Stockpilot Inventory Synchronization"

    def _trigger_stock_update(self, product):
        """Main method to update stock in Stockpilot"""
        _logger.info(
            f"Attempting to sync product: {product.id} - {product.default_code}"
        )

        config = self.env["stockpilot.configuration"].get_config()
        if not config:
            _logger.error("No Stockpilot configuration found")
            return False
        if not product.default_code:
            _logger.error(f"Product {product.id} has no default code (SKU)")
            return False

        try:
            length = getattr(product, "length", 0.0)
            width = getattr(product, "width", 0.0)
            height = getattr(product, "height", 0.0)
            weight = getattr(product, "weight", 0.0)
            payload = {
                "title": product.name,
                "description": product.description or "",
                "product_id": 203,
                "item_name": product.name,
                "sku": product.default_code,
                "barcode": product.barcode or "N/A",
                "barcode_type": "EAN",
                "quantity": int(product.qty_available),
                "moq": 1,
                "stock_threshold": 1,
                "purchase_price": float(product.standard_price),
                "wholesale_price": float(product.standard_price),
                "retail_price": float(product.list_price),
                "weight": str(weight) if product.weight else "0",
                "length": float(length or 0),
                "width": float(width or 0),
                "height": float(height or 0),
                "condition": "NEW",
                "vat_class": "standard_rate",
                "is_active": product.active,
            }

            _logger.debug(f"Payload for {product.default_code}: {payload}")

            response = self._call_stockpilot_api(config, "inventory/create", payload)

            _logger.debug(f"API Response: {response}")

            if response and response.get("product_id"):
                _logger.info(f"Successfully synced product {product.default_code}")
                return True

            _logger.error(f"Unexpected response format for {product.default_code}")
            return False

        except Exception as e:
            _logger.error(f"Failed to sync product {product.default_code}: {str(e)}")
            return False

    def _call_stockpilot_api(self, config, endpoint, data=None, method="POST"):
        """Generic API call handler with detailed error reporting"""
        endpoint_map = {
            "inventory/create": "/inventory/create",
            "inventory/update": "/inventory/update",
            "product/create": "/product/create",
            "inventory/list": "/inventory",
        }

        if endpoint not in endpoint_map:
            raise UserError(_("Unknown API endpoint: %s") % endpoint)

        url = f"{config.base_url.rstrip('/')}{endpoint_map[endpoint]}"
        headers = {
            "X-CLIENT-ID": config.api_client_id,
            "X-CLIENT-SECRET": config.api_client_secret,
            "Content-Type": "application/json",
        }

        try:
            _logger.info(f"Calling {method} {url}")
            _logger.debug(f"Request payload: {data}")

            response = requests.request(
                method, url, json=data, headers=headers, timeout=15
            )

            _logger.debug(f"API response: {response.status_code} - {response.text}")

            # Handle 400 errors specifically
            if response.status_code == 400:
                error_msg = f"Bad Request: {response.text}"
                try:
                    error_data = response.json()
                    if "detail" in error_data:
                        error_msg += f"\nDetails: {error_data['detail']}"
                except Exception as e:
                    _logger.error(f"Failed to parse error response: {str(e)}")
                raise UserError(_(error_msg))

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            if hasattr(e, "response") and e.response:
                error_msg += f"\nResponse: {e.response.text}"
            _logger.error(error_msg)
            raise UserError(_("Stockpilot API Error: %s") % error_msg)

    def _scheduled_full_sync(self):
        """Periodic full synchronization"""
        config = self.env["stockpilot.configuration"].get_config()
        if not config:
            return

        products = self.env["product.product"].search(
            [
                ("type", "=", "product"),
                ("default_code", "!=", False),
                ("active", "=", True),
            ]
        )

        for product in products:
            try:
                self._trigger_stock_update(product)
            except Exception:
                continue

    def _create_stockpilot_product(self, product, config):
        """Create a new product in Stockpilot"""
        product_data = {
            "title": product.name,
            "description": product.description or "",
            "is_active": product.active,
        }

        response = self._call_stockpilot_api(config, "product/create", product_data)
        return response.get("id")

    def _update_stockpilot_inventory_item(self, product, config, update_fields=None):
        """Update an existing inventory item in Stockpilot"""
        if update_fields is None:
            update_fields = {}

        base_data = {
            "sku": product.default_code,
            "quantity": int(product.qty_available),
            "retail_price": product.list_price,
            "purchase_price": product.standard_price,
            "weight": str(product.weight) if product.weight else None,
            "is_active": product.active,
        }
        base_data.update(update_fields)

        payload = {k: v for k, v in base_data.items() if v is not None}

        return self._call_stockpilot_api(
            config, "inventory/update", payload, method="PUT"
        )

    def import_stock_levels(self, config):
        """Stock import with proper stock updates"""
        try:
            _logger.info("=== Starting stock import ===")

            # Get inventory data
            inventory = self._get_stockpilot_inventory(config)
            if not inventory:
                _logger.error("No inventory data received")
                return {"updated": 0, "failed": 0}

            # Get stock location
            location = self._get_stock_location(config.company_id)
            if not location:
                _logger.error("No stock location found")
                return {"updated": 0, "failed": len(inventory) if inventory else 1}

            Product = self.env["product.product"]
            updated = failed = 0

            for item in inventory:
                try:
                    # Clean and prepare identifiers
                    sku = (item.get("sku") or "").strip().upper()
                    barcode = (item.get("barcode") or "").strip()

                    if not sku and not barcode:
                        _logger.warning("Item has no SKU or barcode: %s", item)
                        failed += 1
                        continue

                    # Search product - try multiple methods
                    product = None
                    if sku:
                        product = Product.search(
                            [
                                "|",
                                ("default_code", "=ilike", sku),
                                ("barcode", "=", sku),
                                ("type", "=", "product"),
                            ],
                            limit=1,
                        )

                    if not product and barcode:
                        product = Product.search(
                            [("barcode", "=", barcode), ("type", "=", "product")],
                            limit=1,
                        )

                    if not product:
                        _logger.info(
                            "Product not found for SKU: %s or barcode: %s", sku, barcode
                        )
                        failed += 1
                        continue

                    # Get quantities
                    qty = float(item.get("quantity", 0))
                    reserved = float(item.get("reserved", 0))
                    available = qty - reserved

                    # Update stock using the new method
                    if self._update_stock_quant(product, location, available):
                        updated += 1
                        _logger.debug(
                            "Updated %s to %s", product.default_code, available
                        )
                    else:
                        failed += 1
                        _logger.error(
                            "Failed to update stock for %s", product.default_code
                        )

                except Exception as e:
                    failed += 1
                    _logger.error(
                        "Failed to update %s: %s", sku or barcode, str(e), exc_info=True
                    )

            _logger.info("Import complete: %s updated, %s failed", updated, failed)
            return {"updated": updated, "failed": failed}

        except Exception as e:
            _logger.error("Import failed: %s", str(e), exc_info=True)
            return {"updated": 0, "failed": len(inventory) if inventory else 1}

    def _get_stockpilot_inventory(self, config):
        """Fetch inventory with better response handling"""
        try:
            _logger.info("Fetching inventory from Stockpilot")

            response = self._call_stockpilot_api(
                config,
                "inventory/list",
                {"page_size": 200},  # Increased page size
                method="GET",
            )

            # Debug log the raw response
            _logger.debug("Raw API response: %s", response)

            # Handle different response formats
            if isinstance(response, list):
                return response
            if "data" in response:
                return response["data"]
            if "items" in response:
                return response["items"]
            if "results" in response:
                return response["results"]

            _logger.error("Unknown API response format: %s", response)
            return []

        except Exception as e:
            _logger.error("Failed to fetch inventory: %s", str(e))
            return None

    def _update_product_from_inventory(self, item, Product):
        """Update a single product from inventory data with flexible field mapping"""
        try:
            # Try different possible SKU fields
            sku = (
                item.get("sku")
                or item.get("default_code")
                or item.get("code")
                or item.get("product_code")
            )
            if not sku:
                _logger.warning("Item has no identifiable SKU: %s", item)
                return False

            # Try different possible quantity fields
            quantity = float(
                item.get("quantity")
                or item.get("qty")
                or item.get("available_qty")
                or item.get("stock")
                or 0
            )

            # Try different possible reserved fields
            reserved = float(
                item.get("reserved")
                or item.get("committed")
                or item.get("outgoing_qty")
                or 0
            )

            product = Product.search([("default_code", "=", sku)], limit=1)
            if not product:
                _logger.info("Product not found for SKU: %s", sku)
                return False

            # Prepare update data
            update_vals = {"qty_available": quantity, "outgoing_qty": reserved}

            # Only update if there are changes
            if product.qty_available != quantity or product.outgoing_qty != reserved:
                product.write(update_vals)
                _logger.info(
                    "Updated product %s: qty=%s, reserved=%s",
                    product.default_code,
                    quantity,
                    reserved,
                )
                return True
            else:
                _logger.debug("No changes for product %s", product.default_code)
                return False

        except Exception as e:
            _logger.error("Failed to update product: %s", str(e), exc_info=True)
            return False

    def _update_product_stock(self, product, new_qty):
        """More reliable stock update method with better location handling"""
        try:
            # Get all internal locations for the company
            locations = self.env["stock.location"].search(
                [("usage", "=", "internal"), ("company_id", "=", product.company_id.id)]
            )

            if not locations:
                # Create a default location if none exists
                main_warehouse = self.env["stock.warehouse"].search(
                    [("company_id", "=", product.company_id.id)], limit=1
                )

                if not main_warehouse:
                    raise UserError(
                        _("No warehouse found for company %s") % product.company_id.name
                    )

                main_location = main_warehouse.lot_stock_id
            else:
                # Use the first internal location found
                main_location = locations[0]

            # Use inventory adjustment to properly update stock
            self.env["stock.quant"].with_context(inventory_mode=True).create(
                {
                    "product_id": product.id,
                    "location_id": main_location.id,
                    "inventory_quantity": new_qty,
                }
            )

            # Force quantities recomputation
            product.invalidate_recordset(["qty_available", "outgoing_qty"])
            product._compute_quantities()

            _logger.info(
                "Successfully updated stock for %s to %s at location %s",
                product.default_code,
                new_qty,
                main_location.name,
            )

        except Exception as e:
            _logger.error(
                "Failed to update stock for %s: %s",
                product.default_code,
                str(e),
                exc_info=True,
            )
            raise

    def _get_stock_location(self, company):
        """Get or create stock location for a company"""
        try:
            # First try to get the main company warehouse location
            warehouse = self.env["stock.warehouse"].search(
                [("company_id", "=", company.id)], order="id", limit=1
            )

            if warehouse:
                return warehouse.lot_stock_id

            # If no warehouse exists, create one
            warehouse = self.env["stock.warehouse"].create(
                {
                    "name": company.name + " Warehouse",
                    "code": company.name[:3].upper(),
                    "company_id": company.id,
                }
            )
            return warehouse.lot_stock_id

        except Exception as e:
            _logger.error("Failed to get stock location: %s", str(e))
            raise UserError(
                _(
                    "Could not determine stock location. Please create a warehouse first."
                )
            )

    def _update_stock_quant(self, product, location, quantity):
        """
        Update stock quantity for a product at a specific location
        Uses inventory adjustment to properly update stock levels
        """
        try:
            # Find existing quant or create new one
            quant = self.env["stock.quant"].search(
                [("product_id", "=", product.id), ("location_id", "=", location.id)],
                limit=1,
            )

            if quant:
                # Update existing quant
                quant.sudo().write({"inventory_quantity": quantity})
            else:
                # Create new quant
                self.env["stock.quant"].sudo().create(
                    {
                        "product_id": product.id,
                        "location_id": location.id,
                        "inventory_quantity": quantity,
                    }
                )

            # Force quantities recomputation
            product.invalidate_recordset(["qty_available", "outgoing_qty"])
            product._compute_quantities()

            _logger.info(
                "Updated stock for %s to %s at %s",
                product.default_code,
                quantity,
                location.name,
            )
            return True

        except Exception as e:
            _logger.error(
                "Failed to update stock for %s: %s",
                product.default_code,
                str(e),
                exc_info=True,
            )
            return False

    def _get_stock_location(self, company):
        """Get the main stock location for a company"""
        try:
            # First try to get the main company warehouse
            warehouse = self.env["stock.warehouse"].search(
                [("company_id", "=", company.id)], order="id", limit=1
            )

            if warehouse:
                return warehouse.lot_stock_id

            # If no warehouse exists, get any internal location
            location = self.env["stock.location"].search(
                [("usage", "=", "internal"), ("company_id", "=", company.id)], limit=1
            )

            if location:
                return location

            raise UserError(_("No stock location found for company %s") % company.name)

        except Exception as e:
            _logger.error("Failed to get stock location: %s", str(e))
            return None
