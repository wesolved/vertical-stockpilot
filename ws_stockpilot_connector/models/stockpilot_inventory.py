from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging
import time
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

_logger = logging.getLogger(__name__)

class StockpilotInventory(models.Model):
    _name = 'stockpilot.inventory'
    _description = 'Stockpilot Inventory Synchronization'

    _last_sync = {}

    def _should_sync_product(self, product):
        """Determine if we should sync this product right now"""
        now = time.time()
        last_sync = self._last_sync.get(product.id, 0)
        if now - last_sync < 300:  # 5 minute cooldown
            _logger.debug(f"Skipping sync for {product.default_code}, recently synced")
            return False
        return True

    def _fetch_stockpilot_inventory(self):
        """Main inventory sync method similar to orders sync"""
        _logger.info("=== Starting Stockpilot inventory sync ===")

        configs = self.env['stockpilot.configuration'].search([])
        if not configs:
            _logger.error("No Stockpilot configurations found")
            return False

        results = {
            'updated': 0,
            'created': 0,
            'failed': 0
        }

        for config in configs:
            try:
                _logger.info(f"Processing config for company: {config.company_id.name}")

                inventory_data = self._get_stockpilot_inventory(config)
                if not inventory_data:
                    _logger.warning("No inventory data received from API")
                    continue

                for item in inventory_data:
                    try:
                        result = self._process_inventory_item(item, config.company_id)
                        results[result] += 1
                    except Exception as e:
                        results['failed'] += 1
                        _logger.error(f"Failed to process item: {str(e)}")

                config.last_inventory_sync = fields.Datetime.now()
                _logger.info(f"Completed sync for {config.company_id.name}")

            except Exception as e:
                _logger.error(f"Error processing config {config.id}: {str(e)}")
                results['failed'] += len(inventory_data) if inventory_data else 1
                continue

        _logger.info(f"Inventory sync complete: {results}")
        return results

    def _process_inventory_item(self, item, company):
        """Process single inventory item similar to order processing"""
        try:
            product = self._find_or_create_product(item, company)
            if not product:
                return 'failed'

            if self._update_product_stock(product, item, company):
                return 'created' if getattr(product, '_is_new', False) else 'updated'
            return 'failed'

        except Exception as e:
            _logger.error(f"Error processing item: {str(e)}")
            return 'failed'

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

    def _find_or_create_product(self, item, company):
        """Find or create product from inventory data"""
        sku = (item.get('sku') or '').strip().upper()
        barcode = (item.get('barcode') or '').strip()
        product_name = item.get('title', 'Unknown Product').strip()

        if not sku and not barcode:
            _logger.warning(f"Skipping item with no SKU/barcode: {item}")
            return None

        domain = [
            ('type', '=', 'product'),
            ('company_id', '=', company.id)
        ]

        product = None
        if sku:
            product = self.env['product.product'].search(
                [('default_code', '=', sku)] + domain,
                limit=1
            )

        if not product and barcode:
            product = self.env['product.product'].search(
                [('barcode', '=', barcode)] + domain,
                limit=1
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
            'name': item.get('title', 'Unknown Product'),
            'type': 'product',
            'default_code': item.get('sku'),
            'barcode': item.get('barcode'),
            'standard_price': float(item.get('purchase_price', 0)),
            'list_price': float(item.get('retail_price', 0)),
            'company_id': company.id,
        }
        return self.env['product.product'].create(product_vals)

    def _update_product_stock(self, product, item, company):
        """Update product stock levels"""
        try:
            location = self._get_stock_location(company)
            if not location:
                _logger.error(f"No stock location for company {company.name}")
                return False

            qty = float(item.get('quantity', 0))
            return self._update_stock_quant(product, location, qty)
        except Exception as e:
            _logger.error(f"Failed to update stock: {str(e)}")
            return False

    def _get_stockpilot_inventory(self, config, max_retries=3):
        """Fetch inventory with robust error handling and retries"""
        retry_delay = 1  # Start with 1 second delay

        for attempt in range(max_retries):
            try:
                _logger.info("Fetching inventory (attempt %d/%d)", attempt + 1, max_retries)

                response = self._call_stockpilot_api(
                    config,
                    'inventory/list',
                    {'page_size': 200},
                    method='GET'
                )

                # Handle different response formats
                if isinstance(response, list):
                    _logger.info("Received direct list of %d items", len(response))
                    return response

                if isinstance(response, dict):
                    if 'results' in response:
                        _logger.info("Received %d items in 'results' key", len(response['results']))
                        return response['results']
                    if 'data' in response:
                        _logger.info("Received %d items in 'data' key", len(response['data']))
                        return response['data']
                    if 'items' in response:
                        _logger.info("Received %d items in 'items' key", len(response['items']))
                        return response['items']

                _logger.error("Unsupported response format: %s", type(response))
                return None

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 503 and attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    _logger.warning("Service unavailable (503), retrying in %ds...", wait_time)
                    time.sleep(wait_time)
                    continue
                raise
            except Exception as e:
                _logger.error("API request failed: %s", str(e))
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                raise

        return None

    def _call_stockpilot_api(self, config, endpoint, data=None, method='POST'):
        """Enhanced API call with retry logic"""
        endpoint_map = {
            'inventory/create': '/inventory/create',
            'inventory/update': '/inventory/update',
            'product/create': '/product/create',
            'inventory/list': '/inventory',
        }

        url = f"{config.base_url.rstrip('/')}{endpoint_map.get(endpoint, endpoint)}"
        headers = {
            'X-CLIENT-ID': config.api_client_id,
            'X-CLIENT-SECRET': config.api_client_secret,
            'Content-Type': 'application/json'
        }

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)

        try:
            _logger.info(f"Calling {method} {url}")
            with requests.Session() as session:
                session.mount("https://", adapter)
                response = session.request(
                    method,
                    url,
                    json=data,
                    headers=headers,
                    timeout=15
                )
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
        """Complete stock import with robust error handling"""
        inventory_items = []
        results = {'updated': 0, 'created': 0, 'failed': 0}

        try:
            _logger.info("=== Starting stock import ===")

            try:
                inventory_response = self._get_stockpilot_inventory(config)
                if not inventory_response:
                    _logger.error("No inventory data received from API")
                    return {'updated': 0, 'created': 0, 'failed': 0}

                if isinstance(inventory_response, (list, dict)):
                    if isinstance(inventory_response, dict):
                        # Try all possible keys that might contain the items
                        for key in ['results', 'data', 'items']:
                            if key in inventory_response:
                                inventory_items = inventory_response[key]
                                break
                    else:
                        inventory_items = inventory_response

                    if not inventory_items:
                        _logger.error("No inventory items found in response")
                        return {'updated': 0, 'created': 0, 'failed': 0}

                    _logger.info("Processing %d inventory items", len(inventory_items))
                else:
                    _logger.error("Unexpected response format: %s", type(inventory_response))
                    return {'updated': 0, 'created': 0, 'failed': 0}

            except Exception as e:
                _logger.error("Failed to get inventory: %s", str(e), exc_info=True)
                raise UserError(_("Failed to fetch inventory: %s") % str(e))

            try:
                location = self._get_stock_location(config.company_id)
                if not location:
                    _logger.error("No stock location available")
                    return {'updated': 0, 'created': 0, 'failed': len(inventory_items)}
            except Exception as e:
                _logger.error("Failed to get stock location: %s", str(e))
                return {'updated': 0, 'created': 0, 'failed': len(inventory_items)}

            Product = self.env['product.product']
            processed_skus = set()

            for item in inventory_items:
                try:
                    sku = (item.get('sku') or '').strip().upper()
                    if not sku:
                        _logger.warning("Skipping item with no SKU: %s", item.get('id', 'unknown'))
                        results['failed'] += 1
                        continue

                    if sku in processed_skus:
                        _logger.debug("Skipping duplicate SKU: %s", sku)
                        continue

                    processed_skus.add(sku)
                    _logger.info("Processing product: %s", sku)

                    product = Product.search([
                        ('default_code', '=', sku),
                        ('type', '=', 'product')
                    ], limit=1)

                    if not product:
                        try:
                            product_vals = {
                                'name': item.get('title', 'Product ' + sku),
                                'default_code': sku,
                                'type': 'product',
                                'barcode': item.get('barcode'),
                                'standard_price': float(item.get('purchase_price', 0)),
                                'list_price': float(item.get('retail_price', 0)),
                            }
                            product = Product.create(product_vals)
                            results['created'] += 1
                            _logger.info("Created new product: %s", sku)
                        except Exception as e:
                            _logger.error("Failed to create product %s: %s", sku, str(e))
                            results['failed'] += 1
                            continue

                    try:
                        qty = float(item.get('quantity', 0))
                        if self._update_stock_quant(product, location, qty):
                            results['updated'] += 1
                            _logger.info("Updated stock for %s to %s", sku, qty)
                        else:
                            results['failed'] += 1
                    except Exception as e:
                        results['failed'] += 1
                        _logger.error("Failed to update stock for %s: %s", sku, str(e))

                except Exception as e:
                    results['failed'] += 1
                    _logger.error("Error processing item: %s", str(e), exc_info=True)

            _logger.info("Import complete: %d updated, %d created, %d failed",
                         results['updated'], results['created'], results['failed'])
            return results

        except Exception as e:
            _logger.error("Stock import failed: %s", str(e), exc_info=True)
            return {'updated': 0, 'created': 0, 'failed': len(inventory_items) if inventory_items else 1}

    def _update_product_from_inventory(self, item, Product):
        """Update a single product from inventory data with flexible field mapping"""
        try:
            sku = item.get('sku') or item.get('default_code') or item.get('code') or item.get('product_code')
            if not sku:
                _logger.warning("Item has no identifiable SKU: %s", item)
                return False

            quantity = float(
                item.get('quantity') or item.get('qty') or item.get('available_qty') or item.get('stock') or 0)

            reserved = float(item.get('reserved') or item.get('committed') or item.get('outgoing_qty') or 0)

            product = Product.search([('default_code', '=', sku)], limit=1)
            if not product:
                _logger.info("Product not found for SKU: %s", sku)
                return False

            update_vals = {
                'qty_available': quantity,
                'outgoing_qty': reserved
            }

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

    def _get_stock_location(self, company):
        """Get or create stock location for a company"""
        try:
            warehouse = self.env['stock.warehouse'].search([
                ('company_id', '=', company.id)
            ], order='id', limit=1)

            if warehouse:
                return warehouse.lot_stock_id

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
                quant.sudo().write({'inventory_quantity': quantity})
            else:
                self.env['stock.quant'].sudo().create({
                    'product_id': product.id,
                    'location_id': location.id,
                    'inventory_quantity': quantity
                })

            product.invalidate_recordset(['qty_available', 'outgoing_qty'])
            product._compute_quantities()

            _logger.info("Updated stock for %s to %s at %s",
                        product.default_code, quantity, location.name)
            return True

        except Exception as e:
            _logger.error("Failed to update stock for %s: %s",
                         product.default_code, str(e), exc_info=True)
            return False
