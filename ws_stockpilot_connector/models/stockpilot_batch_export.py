# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Insaf Amrani <insaf.amrani.boukhobza@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
from datetime import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError

# Import will be handled dynamically to avoid circular imports

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

        _logger.info(
            f"[Stockpilot Export] Found {len(products)} products to export: "
            f"{[p.default_code for p in products]}"
        )

        if not products:
            raise UserError(_("No products with SKU found to export"))

        # Use the existing job batch (already created in export_products method)
        job_batch = self.job_batch_id
        if not job_batch:
            raise UserError(_("No job batch found for this export"))

        _logger.info(
            f"[Stockpilot Export] Using job batch: {job_batch.name} (ID: {job_batch.id})"
        )
        _logger.info(
            f"[Stockpilot Export] Batch state before job creation: {job_batch.state}"
        )

        # Ensure batch is in draft state before adding jobs
        if job_batch.state != "draft":
            _logger.warning(
                f"[Stockpilot Export] Batch is not in draft state: {job_batch.state}"
            )

        # Create individual jobs for each product within the batch
        job_count = 0
        for product in products:
            _logger.info(
                f"[Stockpilot Export] Queuing export for product: "
                f"{product.default_code} (ID: {product.id})"
            )
            # Try using the batch object directly in context
            job = (
                self.with_context(job_batch=job_batch)
                .with_delay()
                ._export_single_product(product.id)
            )
            job_count += 1
            _logger.info(f"[Stockpilot Export] Created job {job_count}: {job.uuid}")

        _logger.info(
            f"[Stockpilot Export] Created {job_count} jobs for batch {job_batch.id}"
        )
        _logger.info(
            f"[Stockpilot Export] Batch state after job creation: {job_batch.state}"
        )

        # Refresh the batch to get updated job count
        job_batch.invalidate_recordset()
        _logger.info(
            f"[Stockpilot Export] Batch job count after refresh: {job_batch.job_count}"
        )

        # Enqueue the batch
        job_batch.enqueue()
        _logger.info(
            f"[Stockpilot Export] Batch enqueued. Final state: {job_batch.state}"
        )

        return True

    def _export_single_product(self, product_id):
        """Export a single product or template - this runs as a job within the batch"""
        self.ensure_one()

        Product = self.env["product.product"]
        Template = self.env["product.template"]
        inventory_model = self.env["stockpilot.inventory"]

        # Try to find as a template first
        template = Template.browse(product_id)
        if template and template.exists():
            # Export the template (creates Product Group in Stockpilot)
            try:
                # Export the template (creates Product Group)
                result = inventory_model.with_context(
                    stockpilot_config=self.config_id
                )._trigger_stock_update(template.product_variant_ids[:1])
                # Export all variants (link to Product Group)
                for variant in template.product_variant_ids:
                    inventory_model.with_context(
                        stockpilot_config=self.config_id
                    )._trigger_stock_update(variant)
                _logger.info(
                    _(f"Product template {template.name} exported successfully")
                )
                return True
            except Exception as e:
                error_msg = str(e)
                _logger.error(
                    _(f"Product template {template.name} export error: {error_msg}"),
                    exc_info=True,
                )
                raise  # Always re-raise so the job fails
            return

        # Otherwise, treat as a product variant
        product = Product.browse(product_id)
        try:
            # Check if product should be synced
            if not inventory_model._should_sync_product(product.product_tmpl_id):
                _logger.warning(
                    _(
                        f"Product {product.default_code} skipped - sync conditions not met"
                    )
                )
                return True

            # Check for duplicate EAN
            if self._has_duplicate_ean(product):
                _logger.warning(
                    _(
                        f"Product {product.default_code} skipped -"
                        " duplicate EAN {product.barcode}"
                    )
                )
                return True

            # Attempt to export the product with config context
            result = inventory_model.with_context(
                stockpilot_config=self.config_id
            )._trigger_stock_update(product)

            if result:
                return True
            else:
                return False

        except Exception as e:
            error_msg = str(e)
            _logger.error(
                _(f"Product {product.default_code} export error: {error_msg}"),
                exc_info=True,
            )
            raise  # Always re-raise so the job fails

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
