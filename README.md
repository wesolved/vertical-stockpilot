# Stockpilot Connector

**By WeSolved B.V.**

## Overview

The Stockpilot Connector is an Odoo module developed by WeSolved B.V. that provides seamless integration between Odoo and Stockpilot, a cloud-based inventory and order management platform. This connector synchronizes products, inventory, and sales orders between Odoo and Stockpilot, enabling businesses to automate and streamline their stock and order processes.

## Features

- **Automatic Product Synchronization:**
  - Sync product templates and variants from Odoo to Stockpilot.
  - Handles brands and categories, ensuring your product data is always up to date.

- **Inventory Updates:**
  - Automatically updates Stockpilot with real-time stock levels from Odoo.
  - Triggers updates on stock moves and incoming receipts.

- **Order Import:**
  - Imports sales orders from Stockpilot directly into Odoo.
  - Maps customers and products, creating them on-the-fly if needed.

- **Order Forwarding:**
  - Updates Stockpilot when outgoing deliveries are completed in Odoo.

- **Batch Processing:**
  - Uses Odoo's queue job and batch processing system for reliable, asynchronous communication.

- **Configuration UI:**
  - Manage API credentials, environment, and mappings from the Odoo backend.

## Installation

1. Place the `ws_stockpilot_connector` folder in your Odoo `addons` directory.
2. Ensure the following dependencies are installed in your Odoo instance:
    - `sale_management`
    - `sale_stock`
    - `product_brand` (OCA)
    - `queue_job` (OCA)
    - `queue_job_batch` (OCA)
3. Update the app list and install the "Stockpilot Connector" module from the Odoo Apps menu.

## Configuration

1. Go to **Stockpilot > Configuration** in Odoo.
2. Enter your Stockpilot API credentials and select the desired environment (Test/Production).
3. Configure product, brand, and category mappings as needed.
4. Set up scheduled actions for automatic order import if desired.

## Usage

- **Export Products:** Use the batch export feature to push all products to Stockpilot.
- **Automatic Inventory Sync:** Stock levels are updated in Stockpilot whenever stock moves are completed in Odoo.
- **Order Import:** Orders from Stockpilot are automatically imported and processed in Odoo.
- **Order Forwarding:** When an outgoing delivery is validated, Stockpilot is notified of the shipment.

## Support

For support, feature requests, or bug reports, please contact WeSolved B.V.:
- Website: [https://wesolved.com](https://wesolved.com)
- Email: info@wesolved.com

## License

This module is licensed under the AGPL-3.0 or later (see LICENSE file for details).
