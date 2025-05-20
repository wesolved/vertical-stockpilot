from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging



_logger = logging.getLogger(__name__)
import time

class StockpilotInventory(models.Model):
    _name = 'stockpilot.inventory'
    _description = 'Stockpilot Inventory Synchronization'

    _last_sync = {}

    def _should_sync_product(self, product):
        """Determine if we should sync this product right now"""
        now = time.time()
        last_sync = self._last_sync.get(product.id, 0)

        # Only sync if:
        # 1. Never synced before, OR
        # 2. Last sync was more than 5 minutes ago
        if now - last_sync < 300:  # 5 minute cooldown
            _logger.debug(f"Skipping sync for {product.default_code}, recently synced")
            return False
        return True

    def _trigger_stock_update(self, product):
        """Main method to update stock in Stockpilot"""
        if not self._should_sync_product(product):
            return True

        self._last_sync[product.id] = time.time()
        _logger.info(f"Starting sync for product: {product.id} - {product.default_code}")

        config = self.env['stockpilot.configuration'].get_config()
        if not config:
            _logger.error("No Stockpilot configuration found")
            return False
        if not product.default_code:
            _logger.error(f"Product {product.id} has no default code (SKU)")
            return False

        try:
            length = getattr(product, 'length', 0.0)
            width = getattr(product, 'width', 0.0)
            height = getattr(product, 'height', 0.0)
            weight = getattr(product, 'weight', 0.0)
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
                "is_active": product.active
            }

            _logger.debug(f"Payload for {product.default_code}: {payload}")

            response = self._call_stockpilot_api(
                config,
                'inventory/create',
                payload
            )

            _logger.debug(f"API Response: {response}")

            if response and response.get('product_id'):
                _logger.info(f"Successfully synced product {product.default_code}")
                return True

            _logger.error(f"Unexpected response format for {product.default_code}")
            return False

        except Exception as e:
            _logger.error(f"Failed to sync product {product.default_code}: {str(e)}")
            return False

    def _call_stockpilot_api(self, config, endpoint, data=None, method='POST'):
        """Generic API call handler with detailed error reporting"""
        endpoint_map = {
            'inventory/create': '/inventory/create',
            'inventory/update': '/inventory/update',
            'product/create': '/product/create',
            'inventory/list': '/inventory',
        }

        if endpoint not in endpoint_map:
            raise UserError(_("Unknown API endpoint: %s") % endpoint)

        url = f"{config.base_url.rstrip('/')}{endpoint_map[endpoint]}"
        headers = {
            'X-CLIENT-ID': config.api_client_id,
            'X-CLIENT-SECRET': config.api_client_secret,
            'Content-Type': 'application/json'
        }

        try:
            _logger.info(f"Calling {method} {url}")
            _logger.debug(f"Request payload: {data}")

            response = requests.request(
                method,
                url,
                json=data,
                headers=headers,
                timeout=15
            )

            _logger.debug(f"API response: {response.status_code} - {response.text}")

            # Handle 400 errors specifically
            if response.status_code == 400:
                error_msg = f"Bad Request: {response.text}"
                try:
                    error_data = response.json()
                    if 'detail' in error_data:
                        error_msg += f"\nDetails: {error_data['detail']}"
                except:
                    pass
                raise UserError(_(error_msg))

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response:
                error_msg += f"\nResponse: {e.response.text}"
            _logger.error(error_msg)
            raise UserError(_("Stockpilot API Error: %s") % error_msg)

    def _scheduled_full_sync(self):
        """Periodic full synchronization"""
        config = self.env['stockpilot.configuration'].get_config()
        if not config:
            return

        products = self.env['product.product'].search([
            ('type', '=', 'product'),
            ('default_code', '!=', False),
            ('active', '=', True)
        ])

        for product in products:
            try:
                self._trigger_stock_update(product)
            except Exception as e:
                continue

    def _create_stockpilot_product(self, product, config):
        """Create a new product in Stockpilot"""
        product_data = {
            'title': product.name,
            'description': product.description or '',
            'is_active': product.active
        }

        response = self._call_stockpilot_api(
            config,
            'product/create',
            product_data
        )
        return response.get('id')

    def _update_stockpilot_inventory_item(self, product, config, update_fields=None):
        """Update an existing inventory item in Stockpilot"""
        if update_fields is None:
            update_fields = {}

        base_data = {
            'sku': product.default_code,
            'quantity': int(product.qty_available),
            'retail_price': product.list_price,
            'purchase_price': product.standard_price,
            'weight': str(product.weight) if product.weight else None,
            'is_active': product.active
        }
        base_data.update(update_fields)

        payload = {k: v for k, v in base_data.items() if v is not None}

        return self._call_stockpilot_api(
            config,
            'inventory/update',
            payload,
            method='PUT'
        )

    def import_stock_levels(self, config):
        """Stock import with better error handling and product creation"""
        try:
            _logger.info("=== Starting stock import ===")

            # 1. Get inventory data with error handling
            try:
                inventory = self._get_stockpilot_inventory(config)
                if not inventory:
                    _logger.error("No inventory data received from API")
                    return {'updated': 0, 'created': 0, 'failed': 0}
            except Exception as e:
                _logger.error(f"Failed to fetch inventory: {str(e)}")
                return {'updated': 0, 'created': 0, 'failed': 0}

            # 2. Get or create stock location
            try:
                location = self._get_stock_location(config.company_id)
                if not location:
                    _logger.error("No stock location available")
                    return {'updated': 0, 'created': 0, 'failed': len(inventory)}
            except Exception as e:
                _logger.error(f"Failed to get stock location: {str(e)}")
                return {'updated': 0, 'created': 0, 'failed': len(inventory)}

            Product = self.env['product.product']
            updated = created = failed = 0

            for item in inventory:
                try:
                    # 3. Clean and validate item data
                    sku = (item.get('sku') or '').strip().upper() or None
                    barcode = (item.get('barcode') or '').strip() or None
                    product_name = item.get('title', 'Unknown Product').strip()

                    if not sku and not barcode:
                        _logger.warning(f"Skipping item with no SKU/barcode: {item}")
                        failed += 1
                        continue

                    # 4. Find or create product
                    product = None
                    domain = [('type', '=', 'product')]

                    if sku:
                        product = Product.search([('default_code', '=', sku)] + domain, limit=1)
                    if not product and barcode:
                        product = Product.search([('barcode', '=', barcode)] + domain, limit=1)

                    # Create product if not found
                    if not product:
                        try:
                            product_vals = {
                                'name': product_name,
                                'type': 'product',
                                'default_code': sku,
                                'barcode': barcode,
                                'standard_price': float(item.get('purchase_price', 0)),
                                'list_price': float(item.get('retail_price', 0)),
                            }
                            product = Product.create(product_vals)
                            created += 1
                            _logger.info(f"Created new product: {product_name} ({sku})")
                        except Exception as e:
                            _logger.error(f"Failed to create product {product_name}: {str(e)}")
                            failed += 1
                            continue

                    # 5. Update stock quantities
                    try:
                        qty = float(item.get('quantity', 0))
                        if self._update_stock_quant(product, location, qty):
                            updated += 1
                            _logger.debug(f"Updated {product.default_code} to {qty}")
                        else:
                            failed += 1
                    except Exception as e:
                        _logger.error(f"Failed to update stock for {sku}: {str(e)}")
                        failed += 1

                except Exception as e:
                    failed += 1
                    _logger.error(f"Error processing item {sku}: {str(e)}", exc_info=True)

            _logger.info(f"Import complete: {updated} updated, {created} created, {failed} failed")
            return {'updated': updated, 'created': created, 'failed': failed}

        except Exception as e:
            _logger.error(f"Stock import failed completely: {str(e)}", exc_info=True)
            return {'updated': 0, 'created': 0, 'failed': len(inventory) if inventory else 1}

    def _get_stockpilot_inventory(self, config):
        """Fetch inventory with better response handling"""
        try:
            _logger.info("Fetching inventory from Stockpilot")

            response = self._call_stockpilot_api(
                config,
                'inventory/list',
                {'page_size': 200},  # Increased page size
                method='GET'
            )

            # Debug log the raw response
            _logger.debug("Raw API response: %s", response)

            # Handle different response formats
            if isinstance(response, list):
                return response
            if 'data' in response:
                return response['data']
            if 'items' in response:
                return response['items']
            if 'results' in response:
                return response['results']

            _logger.error("Unknown API response format: %s", response)
            return []

        except Exception as e:
            _logger.error("Failed to fetch inventory: %s", str(e))
            return None
    def _update_product_from_inventory(self, item, Product):
        """Update a single product from inventory data with flexible field mapping"""
        try:
            # Try different possible SKU fields
            sku = item.get('sku') or item.get('default_code') or item.get('code') or item.get('product_code')
            if not sku:
                _logger.warning("Item has no identifiable SKU: %s", item)
                return False

            # Try different possible quantity fields
            quantity = float(
                item.get('quantity') or item.get('qty') or item.get('available_qty') or item.get('stock') or 0)

            # Try different possible reserved fields
            reserved = float(item.get('reserved') or item.get('committed') or item.get('outgoing_qty') or 0)

            product = Product.search([('default_code', '=', sku)], limit=1)
            if not product:
                _logger.info("Product not found for SKU: %s", sku)
                return False

            # Prepare update data
            update_vals = {
                'qty_available': quantity,
                'outgoing_qty': reserved
            }

            # Only update if there are changes
            if (product.qty_available != quantity or
                product.outgoing_qty != reserved):
                product.write(update_vals)
                _logger.info("Updated product %s: qty=%s, reserved=%s",
                             product.default_code, quantity, reserved)
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
            locations = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', product.company_id.id)
            ])

            if not locations:
                # Create a default location if none exists
                main_warehouse = self.env['stock.warehouse'].search([
                    ('company_id', '=', product.company_id.id)
                ], limit=1)

                if not main_warehouse:
                    raise UserError(_("No warehouse found for company %s") % product.company_id.name)

                main_location = main_warehouse.lot_stock_id
            else:
                # Use the first internal location found
                main_location = locations[0]

            # Use inventory adjustment to properly update stock
            self.env['stock.quant'].with_context(inventory_mode=True).create({
                'product_id': product.id,
                'location_id': main_location.id,
                'inventory_quantity': new_qty
            })

            # Force quantities recomputation
            product.invalidate_recordset(['qty_available', 'outgoing_qty'])
            product._compute_quantities()

            _logger.info("Successfully updated stock for %s to %s at location %s",
                         product.default_code, new_qty, main_location.name)

        except Exception as e:
            _logger.error("Failed to update stock for %s: %s",
                          product.default_code, str(e), exc_info=True)
            raise

    def _get_stock_location(self, company):
        """Get or create stock location for a company"""
        try:
            # First try to get the main company warehouse location
            warehouse = self.env['stock.warehouse'].search([
                ('company_id', '=', company.id)
            ], order='id', limit=1)

            if warehouse:
                return warehouse.lot_stock_id

            # If no warehouse exists, create one
            warehouse = self.env['stock.warehouse'].create({
                'name': company.name + ' Warehouse',
                'code': company.name[:3].upper(),
                'company_id': company.id
            })
            return warehouse.lot_stock_id

        except Exception as e:
            _logger.error("Failed to get stock location: %s", str(e))
            raise UserError(_("Could not determine stock location. Please create a warehouse first."))

    def _update_stock_quant(self, product, location, quantity):
        """
        Update stock quantity for a product at a specific location
        Uses inventory adjustment to properly update stock levels
        """
        try:
            # Find existing quant or create new one
            quant = self.env['stock.quant'].search([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id)
            ], limit=1)

            if quant:
                # Update existing quant
                quant.sudo().write({'inventory_quantity': quantity})
            else:
                # Create new quant
                self.env['stock.quant'].sudo().create({
                    'product_id': product.id,
                    'location_id': location.id,
                    'inventory_quantity': quantity
                })

            # Force quantities recomputation
            product.invalidate_recordset(['qty_available', 'outgoing_qty'])
            product._compute_quantities()

            _logger.info("Updated stock for %s to %s at %s",
                        product.default_code, quantity, location.name)
            return True

        except Exception as e:
            _logger.error("Failed to update stock for %s: %s",
                         product.default_code, str(e), exc_info=True)
            return False


    def _get_stock_location(self, company):
        """Get the main stock location for a company"""
        try:
            # First try to get the main company warehouse
            warehouse = self.env['stock.warehouse'].search([
                ('company_id', '=', company.id)
            ], order='id', limit=1)

            if warehouse:
                return warehouse.lot_stock_id

            # If no warehouse exists, get any internal location
            location = self.env['stock.location'].search([
                ('usage', '=', 'internal'),
                ('company_id', '=', company.id)
            ], limit=1)

            if location:
                return location

            raise UserError(_("No stock location found for company %s") % company.name)

        except Exception as e:
            _logger.error("Failed to get stock location: %s", str(e))
            return None
