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

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    total_products = fields.Integer(
        string="Total Products",
        default=0,
        help="Total number of products to be exported",
    )

    successful_exports = fields.Integer(
        string="Successful Exports",
        default=0,
        help="Number of products successfully exported",
    )

    failed_exports = fields.Integer(
        string="Failed Exports",
        default=0,
        help="Number of products that failed to export",
    )

    skipped_exports = fields.Integer(
        string="Skipped Exports",
        default=0,
        help="Number of products skipped due to issues",
    )

    start_date = fields.Datetime(
        string="Start Date",
        help="When the batch export started",
    )

    end_date = fields.Datetime(
        string="End Date",
        help="When the batch export completed",
    )

    log_ids = fields.One2many(
        "stockpilot.batch.export.log",
        "batch_export_id",
        string="Export Logs",
        help="Detailed logs of the export process",
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    def action_start_export(self):
        """Start the batch export process"""
        self.ensure_one()

        if self.state != "draft":
            raise UserError(_("Only draft batches can be started"))

        # Get products to export
        products = self.env["product.product"].search(
            [
                ("type", "=", "product"),
                ("default_code", "!=", False),
                ("active", "=", True),
            ]
        )

        if not products:
            self._log_message("WARNING", "No products with SKU found to export")
            self.write(
                {
                    "state": "completed",
                    "total_products": 0,
                    "end_date": fields.Datetime.now(),
                }
            )
            return True

        self.write(
            {
                "state": "running",
                "total_products": len(products),
                "start_date": fields.Datetime.now(),
            }
        )

        self._log_message(
            "INFO", _("Starting batch export of %d products") % len(products)
        )

        # Execute the batch export
        return self.with_delay()._execute_batch_export(products.ids)

    def _execute_batch_export(self, product_ids):
        """Execute the batch export for all products"""
        self.ensure_one()

        products = self.env["product.product"].browse(product_ids)
        inventory_model = self.env["stockpilot.inventory"]

        successful = 0
        failed = 0
        skipped = 0

        self._log_message("INFO", _("Processing %d products") % len(products))

        for product in products:
            try:
                # Check if product should be synced
                if not inventory_model._should_sync_product(product.product_tmpl_id):
                    self._log_message(
                        "SKIP",
                        _("Product %s skipped - sync conditions not met")
                        % product.default_code,
                    )
                    skipped += 1
                    continue

                # Check for duplicate EAN
                if self._has_duplicate_ean(product):
                    self._log_message(
                        "SKIP",
                        _("Product %s skipped - duplicate EAN %s")
                        % (product.default_code, product.barcode),
                    )
                    skipped += 1
                    continue

                # Attempt to export the product
                result = inventory_model._trigger_stock_update(product)

                if result:
                    successful += 1
                    self._log_message(
                        "SUCCESS",
                        _("Product %s exported successfully") % product.default_code,
                    )
                else:
                    failed += 1
                    self._log_message(
                        "ERROR", _("Product %s export failed") % product.default_code
                    )

            except Exception as e:
                failed += 1
                error_msg = str(e)
                self._log_message(
                    "ERROR",
                    _("Product %s export error: %s")
                    % (product.default_code, error_msg),
                )
                _logger.error(
                    _("Batch export error for product %s: %s")
                    % (product.default_code, error_msg),
                    exc_info=True,
                )

        # Update batch status
        self.write(
            {
                "successful_exports": successful,
                "failed_exports": failed,
                "skipped_exports": skipped,
                "state": "completed" if failed == 0 else "failed",
                "end_date": fields.Datetime.now(),
            }
        )

        # Log final summary
        self._log_message(
            "INFO",
            _("Batch export completed: %d successful, %d failed, %d skipped")
            % (successful, failed, skipped),
        )

        return True

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

    def _log_message(self, level, message):
        """Add a log message to the batch export"""
        self.ensure_one()

        level_mapping = {
            "INFO": "info",
            "SUCCESS": "success",
            "WARNING": "warning",
            "ERROR": "error",
            "SKIP": "warning",
        }

        self.env["stockpilot.batch.export.log"].create(
            {
                "batch_export_id": self.id,
                "level": level_mapping.get(level, "info"),
                "message": message,
                "timestamp": fields.Datetime.now(),
            }
        )

    def action_view_logs(self):
        """Open the logs view for this batch export"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Export Logs - %s") % self.name,
            "res_model": "stockpilot.batch.export.log",
            "view_mode": "tree,form",
            "domain": [("batch_export_id", "=", self.id)],
            "context": {"default_batch_export_id": self.id},
        }

    def action_retry_failed(self):
        """Retry failed exports from this batch"""
        self.ensure_one()

        if self.state not in ["completed", "failed"]:
            raise UserError(_("Only completed or failed batches can be retried"))

        # Get failed products from logs
        failed_logs = self.log_ids.filtered(lambda log: log.level == "error")
        failed_products = []

        for log in failed_logs:
            # Extract product SKU from error message
            if "Product " in log.message and " export" in log.message:
                sku = log.message.split("Product ")[1].split(" ")[0]
                product = self.env["product.product"].search(
                    [
                        ("default_code", "=", sku),
                        ("active", "=", True),
                    ],
                    limit=1,
                )
                if product:
                    failed_products.append(product)

        if not failed_products:
            self._log_message("INFO", "No failed products found to retry")
            return True

        # Create new batch for retry
        retry_batch = self.env["stockpilot.batch.export"].create(
            {
                "name": _("Retry - %s") % self.name,
                "config_id": self.config_id.id,
                "state": "draft",
            }
        )

        retry_batch._log_message(
            "INFO", _("Retrying %d failed products") % len(failed_products)
        )

        # Start retry batch
        return retry_batch.action_start_export()

    def unlink(self):
        """Prevent deletion of running batches"""
        running_batches = self.filtered(lambda b: b.state == "running")
        if running_batches:
            raise UserError(_("Cannot delete running batch exports"))
        return super().unlink()


class StockpilotBatchExportLog(models.Model):
    _name = "stockpilot.batch.export.log"
    _description = "Stockpilot Batch Export Log"
    _order = "timestamp desc"

    batch_export_id = fields.Many2one(
        "stockpilot.batch.export",
        string="Batch Export",
        required=True,
        ondelete="cascade",
    )

    level = fields.Selection(
        [
            ("info", "Info"),
            ("success", "Success"),
            ("warning", "Warning"),
            ("error", "Error"),
        ],
        string="Level",
        required=True,
        default="info",
    )

    message = fields.Text(
        string="Message",
        required=True,
    )

    timestamp = fields.Datetime(
        string="Timestamp",
        default=fields.Datetime.now,
    )

    product_sku = fields.Char(
        string="Product SKU",
        help="SKU of the product this log entry relates to",
    )
