# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductFetchWizard(models.TransientModel):
    _name = "product.fetch.wizard"
    _description = "Product Fetch Wizard"

    configuration_id = fields.Many2one(
        "stockpilot.configuration",
        string="Configuration",
        required=True,
        default=lambda self: self.env.context.get("active_id"),
    )
    
    page_size = fields.Integer(
        string="Page Size",
        default=100,
        help="Number of products to fetch per page",
    )
    
    fetch_all_pages = fields.Boolean(
        string="Fetch All Pages",
        default=True,
        help="If enabled, will fetch all pages of products",
    )
    
    max_pages = fields.Integer(
        string="Max Pages",
        default=10,
        help="Maximum number of pages to fetch (only if Fetch All Pages is disabled)",
    )
    
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("fetching", "Fetching"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="draft",
    )
    
    products_fetched = fields.Integer(
        string="Products Fetched",
        readonly=True,
    )
    
    total_products = fields.Integer(
        string="Total Products",
        readonly=True,
    )
    
    error_message = fields.Text(
        string="Error Message",
        readonly=True,
    )

    def action_fetch_products(self):
        """Fetch products from Stockpilot API"""
        self.ensure_one()
        
        try:
            self.state = "fetching"
            connection = self.configuration_id._get_connection()
            
            page = 1
            total_fetched = 0
            total_count = 0
            
            while True:
                params = {
                    "page": page,
                    "page_size": self.page_size,
                }
                
                _logger.info(f"Fetching products page {page} from Stockpilot API")
                response = connection._execute_get_request("products", params)
                
                if response.status_code != 200:
                    raise UserError(
                        _("Failed to fetch products from Stockpilot API. Status: %s")
                        % response.status_code
                    )
                
                data = response.json()
                total_count = data.get("count", 0)
                results = data.get("results", [])
                
                if not results:
                    break
                
                for product_data in results:
                    self._process_product(product_data)
                    total_fetched += 1
                
                self.products_fetched = total_fetched
                self.total_products = total_count
                
                next_url = data.get("next")
                if not next_url:
                    break
                
                if not self.fetch_all_pages and page >= self.max_pages:
                    break
                
                page += 1
            
            self.state = "done"
            
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Success"),
                    "message": _("Fetched %s products from Stockpilot") % total_fetched,
                    "type": "success",
                    "sticky": False,
                },
            }
            
        except Exception as e:
            self.state = "error"
            self.error_message = str(e)
            _logger.exception("Error fetching products from Stockpilot")
            
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

    def _process_product(self, product_data):
        """Process a single product from the API response"""
        product_obj = self.env["product.product"]
        
        title = product_data.get("title", "")
        description = product_data.get("description", "")
        brand_id = product_data.get("brand")
        category_id = product_data.get("category")
        is_active = product_data.get("is_active", True)
        image_url = product_data.get("image_url")
        
        vals = {
            "name": title,
            "description_sale": description,
            "active": is_active,
        }
        
        existing_product = product_obj.search(
            [("name", "=", title)],
            limit=1,
        )
        
        if existing_product:
            existing_product.write(vals)
            _logger.info(f"Updated product: {title}")
        else:
            product_obj.create(vals)
            _logger.info(f"Created product: {title}")

    def action_close(self):
        """Close the wizard"""
        return {"type": "ir.actions.act_window_close"}
