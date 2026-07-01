# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, *args, **kwargs):
        """
        Call parent method and schedule Stockpilot stock update if transfer is done.

        Returns:
            recordset: Result of the parent _action_done call.
        """
        res = super()._action_done(*args, **kwargs)
        done_moves = self.filtered(lambda m: m.state == "done")
        if not done_moves:
            return res

        moved_products = done_moves.product_id
        # A product whose stock changed may itself be a component in one or
        # more BOMs (kit/phantom or manufacturing). The finished/kit product's
        # available quantity is derived from its components, so it must be
        # resynced whenever a component moves. Walk parents recursively so
        # multi-level BOMs are covered as well.
        products_to_sync = moved_products | done_moves._stockpilot_bom_related_products()

        # Enqueue one job per product so a single failing/unmapped product
        # cannot swallow the updates for the others in the batch.
        for product in products_to_sync:
            product.with_delay()._update_stockpilot_stock()
        return res

    def _stockpilot_bom_related_products(self):
        """
        Collect the finished/kit products that need a stock resync because one
        of the moves in ``self`` touched a component.

        Uses each move's own ``bom_line_id`` when available (the exact BOM the
        move originated from, e.g. an exploded phantom kit) and additionally
        walks the BOM graph upward so that products which merely *contain* a
        moved product as a component are resynced too.

        Returns:
            recordset: product.product records to (re)sync, excluding the
            moved products themselves.
        """
        products = self.env["product.product"]

        # Direct BOM link recorded on the exploded/consumed moves.
        for move in self:
            bom = move.bom_line_id.bom_id
            if bom:
                products |= bom.product_id or bom.product_tmpl_id.product_variant_ids

        # Walk upward through every BOM that uses the moved products.
        products |= self.product_id._stockpilot_get_bom_parent_products()

        return products
