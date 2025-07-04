# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Insaf Amrani <insaf.amrani.boukhobza@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockpilotBatchExport(models.Model):
    _name = "stockpilot.batch.export"
    _description = "Stockpilot Batch Product Export"
    _order = "create_date desc"

    name = fields.Char(
        string="Batch Export Name",
        required=True,
        default=lambda self: _("Batch Export %s")
        % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    config_id = fields.Many2one(
        "stockpilot.configuration",
        string="Stockpilot Configuration",
        required=True,
        ondelete="cascade",
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="config_id.company_id",
        store=True,
    )

    # OCA queue_job_batch integration
    job_batch_id = fields.Many2one(
        "queue.job.batch",
        string="Job Batch",
        help="OCA queue job batch for this export",
        required=True,
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    def action_start_export(self):
        """Start the batch export process using OCA queue_job_batch"""
        self.ensure_one()

        # Get products to export
        products = self.env["product.product"].search(
            [
                ("type", "=", "product"),
                ("default_code", "!=", False),
                ("active", "=", True),
            ]
        )

        if not products:
            raise UserError(_("No products with SKU found to export"))

        # Create OCA job batch
        batch_name = _("Stockpilot Export - %s") % self.name
        job_batch = self.env["queue.job.batch"].get_new_batch(batch_name)

        self.write({"job_batch_id": job_batch.id})

        # Create individual jobs for each product within the batch
        for product in products:
            self.with_context(job_batch=job_batch).with_delay()._export_single_product(
                product.id
            )

        # Enqueue the batch
        job_batch.enqueue()

        return True

    def _export_single_product(self, product_id):
        """Export a single product - this runs as a job within the batch"""
        self.ensure_one()

        product = self.env["product.product"].browse(product_id)
        inventory_model = self.env["stockpilot.inventory"]

        try:
            # Check if product should be synced
            if not inventory_model._should_sync_product(product.product_tmpl_id):
                _logger.warning(
                    _("Product %s skipped - sync conditions not met")
                    % product.default_code
                )
                return True

            # Check for duplicate EAN
            if self._has_duplicate_ean(product):
                _logger.warning(
                    _("Product %s skipped - duplicate EAN %s")
                    % (product.default_code, product.barcode)
                )
                return True

            # Attempt to export the product
            result = inventory_model._trigger_stock_update(product)

            if result:
                _logger.info(
                    _("Product %s exported successfully") % product.default_code
                )
            else:
                _logger.error(_("Product %s export failed") % product.default_code)

        except Exception as e:
            error_msg = str(e)
            _logger.error(
                _("Product %s export error: %s") % (product.default_code, error_msg),
                exc_info=True,
            )
            # Re-raise the exception so the job fails properly in OCA batch
            raise

    def _has_duplicate_ean(self, product):
        """Check if product has duplicate EAN with other products"""
        if not product.barcode:
            return False

        duplicate_count = self.env["product.product"].search_count(
            [
                ("barcode", "=", product.barcode),
                ("id", "!=", product.id),
                ("active", "=", True),
            ]
        )

        return duplicate_count > 0

    def action_view_job_batch(self):
        """Open the OCA job batch view"""
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": _("Job Batch - %s") % self.job_batch_id.name,
            "res_model": "queue.job.batch",
            "view_mode": "form",
            "res_id": self.job_batch_id.id,
            "target": "current",
        }

    def unlink(self):
        """Prevent deletion if job batch is running"""
        running_batches = self.filtered(
            lambda b: b.job_batch_id.state in ["enqueued", "progress"]
        )
        if running_batches:
            raise UserError(_("Cannot delete running batch exports"))
        return super().unlink()
