# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    stockpilot_order_id = fields.Char(
        string='Stockpilot Order ID',
        copy=False,
        help='Original order ID from Stockpilot'
    )

    stockpilot_sync_status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('synced', 'Synced'),
            ('error', 'Error')
        ],
        string='Stockpilot Sync Status',
        default='pending',
        copy=False
    )

    stockpilot_last_sync = fields.Datetime(
        string='Last Sync Date',
        copy=False
    )

    stockpilot_last_error = fields.Text(
        string='Last Sync Error',
        copy=False
    )

    def _get_stockpilot_config(self):
        """Get the Stockpilot configuration for current company"""
        return self.env['stockpilot.configuration'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)

    def _sync_to_stockpilot(self):
        """Sync order to Stockpilot"""
        self.ensure_one()
        config = self._get_stockpilot_config()
        if not config:
            return False

        try:
            response = self._call_stockpilot_api(config, 'orders/update', self._prepare_stockpilot_order_data())

            if response.get('success'):
                self.write({
                    'stockpilot_sync_status': 'synced',
                    'stockpilot_last_sync': fields.Datetime.now(),
                    'stockpilot_last_error': False
                })
                return True
            else:
                error_msg = response.get('message', 'Unknown error from Stockpilot')
                self._handle_sync_error(error_msg)
                return False

        except Exception as e:
            self._handle_sync_error(str(e))
            return False

    def _prepare_stockpilot_order_data(self):
        """Prepare order data for Stockpilot API"""
        self.ensure_one()
        return {
            'order_id': self.stockpilot_order_id or self.id,
            'status': self._get_stockpilot_status(),
            'lines': [{
                'sku': line.product_id.default_code,
                'quantity': line.product_uom_qty,
                'price': line.price_unit,
            } for line in self.order_line if line.product_id.default_code],
        }

    @api.model
    def _map_stockpilot_to_odoo_status(self, stockpilot_status):
        """Map Stockpilot status to Odoo status"""
        status_mapping = {
            'New': 'draft',
            'Processing': 'sale',
            'Shipped': 'done',
            'Cancelled': 'cancel'
        }
        return status_mapping.get(stockpilot_status, 'draft')

    def _get_stockpilot_status(self):
        """Map Odoo status to Stockpilot status"""
        status_mapping = {
            'draft': 'New',
            'sent': 'New',
            'sale': 'Processing',
            'done': 'Shipped',
            'cancel': 'Cancelled'
        }
        return status_mapping.get(self.state, 'New')

    def _handle_sync_error(self, error_msg):
        """Handle synchronization errors"""
        self.ensure_one()
        self.write({
            'stockpilot_sync_status': 'error',
            'stockpilot_last_error': error_msg
        })

    def action_confirm(self):
        """Override confirm to update Stockpilot inventory"""
        res = super(SaleOrder, self).action_confirm()

        if self.stockpilot_order_id:
            self._update_stockpilot_inventory()

        return res

    def _update_stockpilot_inventory(self):
        """Update stock levels in Stockpilot"""
        config = self._get_stockpilot_config()
        if not config:
            return False

        product_ids = self.order_line.mapped('product_id').filtered(lambda p: p.default_code)
        if not product_ids:
            return False

        inventory_data = [{
            'sku': product.default_code,
            'quantity': product.qty_available - product.outgoing_qty
        } for product in product_ids]

        try:
            response = self._call_stockpilot_api(config, 'inventory/update', inventory_data)
            return response.get('success', False)
        except Exception as e:
            return False
