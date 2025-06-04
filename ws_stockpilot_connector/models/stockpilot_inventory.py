import json
import logging
import time

import requests
from odoo import _, models
from odoo.exceptions import UserError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_logger = logging.getLogger(__name__)


class StockpilotInventory(models.Model):
    _name = "stockpilot.inventory"
    _description = "Stockpilot Inventory Synchronization"

    _last_sync = {}

    def _should_sync_product(self, product):
        """Determine if we should sync this product right now"""
        now = time.time()
        last_sync = self._last_sync.get(product.id, 0)
        if now - last_sync < 300:  # 5 minute cooldown
            _logger.debug(f"Skipping sync for {product.default_code}, recently synced")
            return False
        return True

    def _trigger_stock_update(self, product, template_id=None):
        """Handle product and inventory synchronization with Stockpilot (refactored)"""
        product_template = product.product_tmpl_id

        if not self._should_sync_product(product_template):
            return True

        config = self.env["stockpilot.configuration"].get_config()
        if not config:
            _logger.error("No Stockpilot configuration found")
            return False

        default_code = product_template.default_code or product.default_code
        if not default_code:
            _logger.error(f"Product {product_template.id} has no default code (SKU)")
            return False

        try:
            product_id = self._handle_product_header(config, product_template)
            if not product_id:
                return False

            return self._process_variants(
                config, product_template, product_id, default_code
            )

        except Exception as e:
            _logger.error(f"Sync failed: {str(e)}", exc_info=True)
            return False

    def _handle_product_header(self, config, product_template):
        """Handle product header creation/verification"""
        product_id = product_template.stockpilot_id

        if not product_id:
            product_header_payload = {
                "title": product_template.name,
                "description": product_template.description or "",
                "brand": 1,
                "category": 1,
                "is_active": product_template.active,
            }

            _logger.info("Creating product header...")
            header_response = self._call_stockpilot_api(
                config, "/products/create", product_header_payload, method="POST"
            )

            if not header_response or not header_response.get("product_id"):
                _logger.error("Product header creation failed")
                return False

            product_id = header_response["product_id"]
            if not self._verify_product(config, product_id):
                return False

            product_template.stockpilot_id = product_id
            _logger.info(f"Verified product header with ID: {product_id}")

        return product_id

    def _verify_product(self, config, product_id):
        """Verify product exists in Stockpilot"""
        try:
            verify_response = self._call_stockpilot_api(
                config, "/products/get", method="GET", params={"id": product_id}
            )
            if not verify_response:
                _logger.error(f"Product {product_id} verification failed")
                return False
            return True
        except Exception as e:
            _logger.error(f"Product verification error: {str(e)}")
            return False

    def _process_variants(self, config, product_template, product_id, default_code):
        """Process all variants of a product"""
        all_success = True

        for variant in product_template.product_variant_ids:
            variant_result = self._process_single_variant(
                config, variant, product_id, default_code
            )
            product_template.product_variant_ids.write({'exported_to_stockpilot': True})
            if not variant_result:
                all_success = False

        if all_success:
            product_template.exported_to_stockpilot = True
        return all_success

    def _process_single_variant(self, config, variant, product_id, default_code):
        """Process a single product variant"""
        variant_code = variant.default_code or default_code
        barcode = variant.barcode or "N/A"

        try:
            existing_inventory = self._get_existing_inventory(
                config, variant, variant_code, barcode
            )

            inventory_payload = self._prepare_inventory_payload(
                variant, product_id, variant_code, barcode
            )

            if existing_inventory and existing_inventory.get("id"):
                return self._update_inventory(
                    config, existing_inventory["id"], inventory_payload, variant_code
                )
            else:
                return self._create_inventory(
                    config, inventory_payload, variant, variant_code
                )

        except Exception as e:
            _logger.error(f"Error processing variant {variant_code}: {str(e)}")
            return False

    def _get_existing_inventory(self, config, variant, variant_code, barcode):
        """Check for existing inventory in Stockpilot"""
        if variant.stockpilot_id:
            try:
                return self._call_stockpilot_api(
                    config,
                    "/inventory/get",
                    method="GET",
                    params={"id": variant.stockpilot_id},
                )
            except Exception:
                pass

        try:
            return self._call_stockpilot_api(
                config,
                "/inventory/get",
                method="GET",
                params={"sku": variant_code, "barcode": barcode},
            )
        except Exception:
            return None

    def _prepare_inventory_payload(self, variant, product_id, variant_code, barcode):
        """Prepare inventory payload for API call"""
        return {
            "product_id": product_id,
            "title": variant.name,
            "description": variant.description or "",
            "item_name": variant.name,
            "sku": variant_code,
            "barcode": barcode,
            "barcode_type": "EAN",
            "quantity": int(variant.qty_available),
            "moq": 1,
            "stock_threshold": 1,
            "purchase_price": round(float(variant.standard_price), 2),
            "wholesale_price": round(float(variant.standard_price), 2),
            "retail_price": float(variant.list_price),
            "weight": str(variant.weight) if variant.weight else "0",
            "condition": "NEW",
            "vat_class": "standard_rate",
            "is_active": variant.active,
        }

    def _update_inventory(self, config, inventory_id, payload, variant_code):
        """Update existing inventory item"""
        payload["product_id"] = inventory_id
        response = self._call_stockpilot_api(
            config, "/inventory/update", payload, method="POST"
        )
        if response and response.get("product_id"):
            _logger.info(f"Successfully updated inventory for {variant_code}")
            return True
        _logger.error(f"Failed to update inventory for {variant_code}")
        return False

    def _create_inventory(self, config, payload, variant, variant_code):
        """Create new inventory item"""
        response = self._call_stockpilot_api(
            config, "/inventory/create", payload, method="POST"
        )
        if response and response.get("product_id"):
            variant.stockpilot_id = response["product_id"]
            variant.exported_to_stockpilot = True
            _logger.info(f"Successfully created inventory for {variant_code}")
            return True
        _logger.error(f"Failed to create inventory for {variant_code}")
        return False

    def _find_or_create_product(self, item, company):
        """Find or create product from inventory data"""
        sku = (item.get("sku") or "").strip().upper()
        barcode = (item.get("barcode") or "").strip()
        product_name = item.get("title", "Unknown Product").strip()

        if not sku and not barcode:
            _logger.warning(f"Skipping item with no SKU/barcode: {item}")
            return None

        domain = [("type", "=", "product"), ("company_id", "=", company.id)]

        product = None
        if sku:
            product = self.env["product.product"].search(
                [("default_code", "=", sku)] + domain, limit=1
            )

        if not product and barcode:
            product = self.env["product.product"].search(
                [("barcode", "=", barcode)] + domain, limit=1
            )

        if not product:
            try:
                product = self._create_product_from_inventory(item, company)
                product._is_new = True  # Mark as new for tracking
                _logger.info(f"Created new product: {product_name} ({sku})")
            except Exception as e:
                _logger.error(f"Failed to create product: {str(e)}")
                return None

        return product

    def _create_product_from_inventory(self, item, company):
        """Create new product from inventory data"""
        product_vals = {
            "name": item.get("title", "Unknown Product"),
            "type": "product",
            "default_code": item.get("sku"),
            "barcode": item.get("barcode"),
            "standard_price": float(item.get("purchase_price", 0)),
            "list_price": float(item.get("retail_price", 0)),
            "company_id": company.id,
        }
        return self.env["product.product"].create(product_vals)

    def _update_product_stock(self, product, item, company):
        """Update product stock levels"""
        try:
            location = self._get_stock_location(company)
            if not location:
                _logger.error(f"No stock location for company {company.name}")
                return False

            qty = float(item.get("quantity", 0))
            return self._update_stock_quant(product, location, qty)
        except Exception as e:
            _logger.error(f"Failed to update stock: {str(e)}")
            return False

    def _call_stockpilot_api(
        self, config, endpoint, data=None, method="POST", params=None
    ):
        """Enhanced API call that handles both POST and GET requests"""
        base_url = config.base_url.rstrip("/")
        url = f"{base_url}{endpoint}"

        headers = {
            "X-CLIENT-ID": config.api_client_id,
            "X-CLIENT-SECRET": config.api_client_secret,
            "Content-Type": "application/json",
        }

        _logger.info(f"[Stockpilot] Calling {method} {url}")
        if params:
            _logger.info(f"[Stockpilot] Params: {params}")
        if data:
            _logger.info(f"[Stockpilot] Payload: {json.dumps(data, indent=2)}")

        try:
            with requests.Session() as session:
                # Configure retry strategy
                retry_strategy = Retry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=[500, 502, 503, 504],
                    allowed_methods=["GET", "POST", "PUT"],
                )
                adapter = HTTPAdapter(max_retries=retry_strategy)
                session.mount("https://", adapter)

                if method.upper() == "GET":
                    response = session.get(
                        url, headers=headers, params=params, timeout=15
                    )
                else:
                    response = session.request(
                        method, url, json=data, headers=headers, timeout=15
                    )

                response.raise_for_status()
                _logger.info(
                    f"[Stockpilot] Response: {response.status_code} {response.text}"
                )
                return response.json()

        except requests.exceptions.RequestException as e:
            error_msg = (
                f"Stockpilot API Error: {e.response.status_code} {e.response.reason}"
            )
            if e.response.text:
                error_msg += f"\n{e.response.text}"
            _logger.error(error_msg)
            raise UserError(_(error_msg))
        except Exception as e:
            _logger.exception("[Stockpilot] Unexpected error calling API")
            raise UserError(_("Unexpected error calling Stockpilot API: %s") % str(e))

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

    def import_stockpilot_products(self):
        """Import products from Stockpilot by syncing known IDs"""
        config = self.env["stockpilot.configuration"].get_config()
        if not config:
            raise UserError(_("No Stockpilot configuration found"))

        results = {"created": 0, "updated": 0, "failed": 0}

        # Get all products we know about in Stockpilot
        known_products = self.env["product.template"].search(
            [("stockpilot_id", "!=", False)]
        )

        for product in known_products:
            try:
                # 1. Get product data
                product_data = self._get_product_by_id(config, product.stockpilot_id)
                if not product_data:
                    results["failed"] += 1
                    continue

                # 2. Update product data
                product.write(
                    {
                        "name": product_data.get("title", product.name),
                        "description": product_data.get(
                            "description", product.description
                        ),
                        "active": product_data.get("is_active", product.active),
                    }
                )

                # 3. Process inventory for each variant
                for variant in product.product_variant_ids:
                    try:
                        # Try to get inventory by variant's stored Stockpilot ID first
                        inventory_data = None
                        if variant.stockpilot_id:
                            try:
                                inventory_data = self._get_inventory_item(
                                    config, id=variant.stockpilot_id
                                )
                            except Exception as e:
                                _logger.debug(
                                    f"Failed to get ID {variant.stockpilot_id}: {str(e)}"
                                )

                        # If not found by ID, try by SKU or barcode
                        if not inventory_data:
                            try:
                                inventory_data = self._get_inventory_item(
                                    config,
                                    sku=variant.default_code,
                                    barcode=variant.barcode,
                                )
                            except Exception as e:
                                _logger.debug(
                                    f"Failed to get inventory by SKU/barcode: {str(e)}"
                                )

                        if inventory_data:
                            self._process_inventory_item(
                                product, inventory_data, results
                            )
                            results["updated"] += 1
                        else:
                            _logger.warning(
                                f"No inventory data found for variant {variant.id}"
                            )
                            results["failed"] += 1

                    except Exception as e:
                        results["failed"] += 1
                        _logger.error(
                            f"Error processing variant {variant.id}: {str(e)}",
                            exc_info=True,
                        )

            except Exception as e:
                results["failed"] += 1
                _logger.error(
                    f"Error processing product {product.stockpilot_id}: {str(e)}",
                    exc_info=True,
                )

        return results

    def _get_inventory_item(self, config, **kwargs):
        """Get inventory item by ID, SKU, or barcode"""
        valid_params = {}
        for param in ["id", "sku", "barcode"]:
            if param in kwargs and kwargs[param]:
                valid_params[param] = kwargs[param]

        if not valid_params:
            raise ValueError("At least one of id, sku, or barcode must be provided")

        return self._call_stockpilot_api(
            config, "/inventory/get", method="GET", params=valid_params
        )

    def _get_product_by_id(self, config, product_id):
        """Get single product by ID"""
        return self._call_stockpilot_api(
            config, "/products/get", method="GET", params={"id": product_id}
        )

    def _process_inventory_item(self, product_template, item_data, results=None):
        """Process single inventory item with duplicate variant checking"""
        # First try to find by stockpilot_id
        variant = self.env["product.product"].search(
            [
                ("stockpilot_id", "=", item_data.get("id")),
                ("product_tmpl_id", "=", product_template.id),
            ],
            limit=1,
        )

        # If not found by stockpilot_id, try to find by SKU
        if not variant and item_data.get("sku"):
            variant = self.env["product.product"].search(
                [
                    ("default_code", "=", item_data.get("sku")),
                    ("product_tmpl_id", "=", product_template.id),
                ],
                limit=1,
            )

        try:
            # Handle barcode uniqueness
            barcode = item_data.get("barcode")
            if barcode == "N/A":
                barcode = False
            elif (
                barcode
                and self.env["product.product"].search_count(
                    [("barcode", "=", barcode)]
                )
                > 0
            ):
                barcode = f"{barcode}-{item_data.get('id')}"

            vals = {
                "default_code": item_data.get("sku"),
                "barcode": barcode,
                "standard_price": float(item_data.get("purchase_price", "0")),
                "list_price": float(item_data.get("retail_price", "0")),
                "weight": float(item_data.get("weight", "0")),
                "qty_available": float(item_data.get("quantity", "0")),
                "stockpilot_id": item_data.get("id"),
                "exported_to_stockpilot": True,
            }

            if variant:
                # Update existing variant
                variant.write(vals)
                if results:
                    results["updated"] += 1
                _logger.info(f"Updated variant {variant.id}")
            else:
                # Create new variant only if it doesn't exist
                vals["product_tmpl_id"] = product_template.id
                self.env["product.product"].create(vals)
                if results:
                    results["created"] += 1
                _logger.info("Created new variant")

        except Exception as e:
            _logger.error(f"Error processing inventory item: {str(e)}")
            if results:
                results["failed"] += 1
            raise UserError(_("Failed to process inventory: %s") % str(e))

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
            except Exception as e:
                _logger.error(f"Failed to sync product {product.id}: {str(e)}")
                continue

    def _get_stockpilot_products(self, config):
        """Fetch all products from Stockpilot"""
        try:
            response = self._call_stockpilot_api(config, "/products/get", method="GET")
            return response if response else []
        except Exception as e:
            _logger.error(f"Failed to get products: {str(e)}")
            return []

    def _process_stockpilot_product(self, config, product_data):
        """Process a single Stockpilot product"""
        existing_product = self.env["product.template"].search(
            [("stockpilot_id", "=", product_data["id"])], limit=1
        )

        if existing_product:
            _logger.info(
                f"Product {product_data['id']} already exists, skipping creation"
            )
            product_template = existing_product
        else:
            product_template = self._create_product_from_stockpilot(product_data)
            _logger.info(f"Created new product template: {product_template.id}")

        self._process_product_variants(config, product_template, product_data["id"])

    def _create_product_from_stockpilot(self, product_data):
        """Create new product template from Stockpilot data"""
        return self.env["product.template"].create(
            {
                "name": product_data["title"],
                "description": product_data.get("description", ""),
                "type": "product",
                "default_code": product_data.get("sku"),
                "stockpilot_id": product_data["id"],
                "exported_to_stockpilot": True,
                "categ_id": self._get_or_create_category(product_data.get("category")),
            }
        )

    def _process_product_variants(self, config, product_template, product_id):
        """Process all variants for a product"""
        inventory_items = self._get_stockpilot_inventory(config, product_id)

        for item in inventory_items:
            try:
                self._process_inventory_item(product_template, item)
            except Exception as e:
                _logger.error(
                    f"Error processing inventory item {item.get('id')}: {str(e)}",
                    exc_info=True,
                )
                continue

    def _get_stockpilot_inventory(self, config, product_id):
        """Get inventory items for a product"""
        try:
            response = self._call_stockpilot_api(
                config,
                "/inventory/get",
                method="GET",
                params={"product_id": product_id},
            )
            return response if response else []
        except Exception as e:
            _logger.error(f"Failed to get inventory for product {product_id}: {str(e)}")
            return []

    def _update_product_variant(self, variant, item_data):
        """Update existing product variant"""
        vals = {
            "default_code": item_data.get("sku"),
            "barcode": item_data.get("barcode"),
            "standard_price": item_data.get("purchase_price", 0),
            "list_price": item_data.get("retail_price", 0),
            "weight": float(item_data.get("weight", 0)),
            "qty_available": item_data.get("quantity", 0),
            "stockpilot_id": item_data["id"],
            "exported_to_stockpilot": True,
        }
        variant.write(vals)

    def _create_product_variant(self, product_template, item_data):
        """Create new product variant"""
        return self.env["product.product"].create(
            {
                "product_tmpl_id": product_template.id,
                "default_code": item_data.get("sku"),
                "barcode": item_data.get("barcode"),
                "standard_price": item_data.get("purchase_price", 0),
                "list_price": item_data.get("retail_price", 0),
                "weight": float(item_data.get("weight", 0)),
                "qty_available": item_data.get("quantity", 0),
                "stockpilot_id": item_data["id"],
                "exported_to_stockpilot": True,
            }
        )

    def _get_or_create_category(self, category_name):
        """Get or create product category"""
        if not category_name:
            return self.env.ref("product.product_category_all").id

        category = self.env["product.category"].search(
            [("name", "=", category_name)], limit=1
        )

        if not category:
            category = self.env["product.category"].create({"name": category_name})

        return category.id

    def _fetch_inventory_items(self, config):
        """Fetch and validate inventory data from API"""
        try:
            response = self._get_stockpilot_inventory(config)
            if not response:
                _logger.error("No inventory data received from API")
                return None

            if isinstance(response, dict):
                for key in ["results", "data", "items"]:
                    if key in response:
                        return response[key]
            elif isinstance(response, list):
                return response

            _logger.error("Unexpected response format: %s", type(response))
            return None
        except Exception as e:
            _logger.error("Failed to get inventory: %s", str(e), exc_info=True)
            raise UserError(_("Failed to fetch inventory: %s") % str(e))

    def _process_single_item(self, item, sku, Product, location, results):
        """Handle processing of a single inventory item"""
        product = Product.search(
            [("default_code", "=", sku), ("type", "=", "product")], limit=1
        )

        if not product:
            product = self._create_product(item, sku, Product, results)
            if not product:
                return

        self.with_delay()._update_product_stocks(product, location, item, results)

    def _create_product(self, item, sku, Product, results):
        """Create new product if doesn't exist"""
        try:
            product_vals = {
                "name": item.get("title", "Product " + sku),
                "default_code": sku,
                "type": "product",
                "barcode": item.get("barcode"),
                "standard_price": float(item.get("purchase_price", 0)),
                "list_price": float(item.get("retail_price", 0)),
            }
            product = Product.create(product_vals)
            results["created"] += 1
            _logger.info("Created new product: %s", sku)
            return product
        except Exception as e:
            _logger.error("Failed to create product %s: %s", sku, str(e))
            results["failed"] += 1
            return None

    def _update_product_stocks(self, product, location, item, results):
        """Update stock quantity for existing product"""
        try:
            qty = float(item.get("quantity", 0))
            if self._update_stock_quant(product, location, qty):
                results["updated"] += 1
                _logger.info("Updated stock for %s to %s", product.default_code, qty)
                product.exported_to_stockpilot = True
            else:
                results["failed"] += 1
        except Exception as e:
            results["failed"] += 1
            _logger.error(
                "Failed to update stock for %s: %s", product.default_code, str(e)
            )

    def _update_product_from_inventory(self, item, Product):
        """Update a single product from inventory data with flexible field mapping"""
        try:
            sku = (
                item.get("sku")
                or item.get("default_code")
                or item.get("code")
                or item.get("product_code")
            )
            if not sku:
                _logger.warning("Item has no identifiable SKU: %s", item)
                return False

            quantity = float(
                item.get("quantity")
                or item.get("qty")
                or item.get("available_qty")
                or item.get("stock")
                or 0
            )

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

            update_vals = {"qty_available": quantity, "outgoing_qty": reserved}

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

    def _get_stock_location(self, company):
        """Get or create stock location for a company"""
        try:
            warehouse = self.env["stock.warehouse"].search(
                [("company_id", "=", company.id)], order="id", limit=1
            )

            if warehouse:
                return warehouse.lot_stock_id

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
                quant.sudo().write({"inventory_quantity": quantity})
            else:
                self.env["stock.quant"].sudo().create(
                    {
                        "product_id": product.id,
                        "location_id": location.id,
                        "inventory_quantity": quantity,
                    }
                )

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
