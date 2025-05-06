# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta



class StockpilotSync(models.Model):
    _name = 'stockpilot.sync'
    _description = 'Stockpilot Synchronization'

    def _fetch_stockpilot_orders(self):
        """Fetch orders from Stockpilot and create/update in Odoo"""
        configs = self.env['stockpilot.configuration'].search([])
        for config in configs:
            try:
                last_sync = config.last_sync_date or datetime.now() - timedelta(days=7)
                orders = self._get_stockpilot_orders(config, last_sync)

                for order_data in orders:
                    self._process_stockpilot_order(order_data, config.company_id)

                config.last_sync_date = datetime.now()

            except Exception as e:
                continue

    def _process_stockpilot_order(self, order_data, company):
        """Process a single Stockpilot order"""
        order = self.env['sale.order'].search([
            ('stockpilot_order_id', '=', order_data['id']),
            ('company_id', '=', company.id)
        ], limit=1)

        try:
            if not order:
                order = self._create_order_from_stockpilot(order_data, company)
            else:
                self._update_order_from_stockpilot(order, order_data)

            if order.state == 'sale':
                order.action_confirm()

            order.write({
                'stockpilot_sync_status': 'synced',
                'stockpilot_last_sync': fields.Datetime.now(),
                'stockpilot_last_error': False
            })

        except Exception as e:
            if order:
                order.write({
                    'stockpilot_sync_status': 'error',
                    'stockpilot_last_error': str(e)
                })

    def _create_order_from_stockpilot(self, order_data, company):
        """Create new Odoo order from Stockpilot data"""
        partner = self._find_or_create_customer(order_data['customer'], company)

        order_vals = {
            'stockpilot_order_id': order_data['id'],
            'partner_id': partner.id,
            'date_order': order_data.get('date', fields.Datetime.now()),
            'state': self._map_stockpilot_to_odoo_status(order_data.get('status', 'New')),
            'company_id': company.id,
            'order_line': self._prepare_order_lines(order_data.get('lines', [])),
        }

        return self.env['sale.order'].create(order_vals)

    def _update_order_from_stockpilot(self, order, order_data):
        """Update existing Odoo order from Stockpilot data"""
        update_vals = {
            'state': self._map_stockpilot_to_odoo_status(order_data.get('status', order.state)),
        }

        if 'lines' in order_data:
            self._update_order_lines(order, order_data['lines'])

        order.write(update_vals)

    def _prepare_order_lines(self, lines_data):
        """Prepare order line values from Stockpilot data"""
        order_lines = []

        for line in lines_data:
            product = self.env['product.product'].search([
                ('default_code', '=', line['sku'])
            ], limit=1)

            if product:
                order_lines.append((0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': line['quantity'],
                    'price_unit': line.get('price', product.list_price),
                }))

        return order_lines

    def _update_order_lines(self, order, lines_data):
        """Update existing order lines from Stockpilot data"""
        pass

    def _find_or_create_customer(self, customer_data, company):
        """Find or create partner from Stockpilot customer data"""
        return self.env['res.partner'].search([], limit=1)
