# Stockpilot Product Fetch

This module extends the Stockpilot Connector to fetch inventory items from the Stockpilot API.

## Features

- Fetch inventory from Stockpilot API endpoint: `https://api.stockpilot.dev/inventory/`
- Smart button on Stockpilot Configuration to trigger inventory fetch
- Wizard interface with configurable options:
  - Page size (number of items per page, default: 50)
  - Fetch all pages or limit to max pages
  - Progress tracking (items fetched / total items)
- Automatic product creation/update in Odoo
- Automatic linking to Stockpilot product mapping
- Error handling and user notifications

## Usage

1. Navigate to Stockpilot > Configurations
2. Open a configuration record
3. Click the "Fetch Products" button in the button box
4. Configure fetch options in the wizard:
   - Set page size (default: 50)
   - Enable/disable fetch all pages
   - Set max pages if not fetching all
5. Click "Fetch Products" to start the import
6. View progress and results in the wizard

## Product Mapping

The module maps Stockpilot inventory fields to Odoo as follows:

- `item_name` → `name`
- `sku` → `default_code` (Internal Reference)
- `barcode` → `barcode`
- `is_active` → `active`
- `id` → `stockpilot.product.product.stockpilot_id` (linked to mapping)

### Product Matching Logic

Products are matched in the following order:
1. By barcode (if provided)
2. By SKU/internal reference (if provided)
3. By name

If a matching product exists, it will be updated; otherwise, a new product is created.

### Stockpilot Mapping

After creating or updating a product, the module automatically:
- Creates or updates a `stockpilot.product.product` record
- Links the Odoo product to the Stockpilot inventory ID
- Associates it with the current configuration

## Dependencies

- ws_stockpilot_connector
- product

## Technical Details

- Model: `product.fetch.wizard` (TransientModel)
- Inherits: `stockpilot.configuration`
- API Endpoint: `GET https://api.stockpilot.dev/inventory/`
- Pagination: Supports paginated responses with `next` URL
- Creates/updates: `product.product` and `stockpilot.product.product` records

## License

LGPL-3
