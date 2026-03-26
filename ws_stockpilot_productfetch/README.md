# Stockpilot Product Fetch

This module extends the Stockpilot Connector to fetch products from the Stockpilot API.

## Features

- Fetch products from Stockpilot API endpoint: `https://api.stockpilot.dev/products/`
- Smart button on Stockpilot Configuration to trigger product fetch
- Wizard interface with configurable options:
  - Page size (number of products per page)
  - Fetch all pages or limit to max pages
  - Progress tracking (products fetched / total products)
- Automatic product creation/update in Odoo
- Error handling and user notifications

## Usage

1. Navigate to Stockpilot > Configurations
2. Open a configuration record
3. Click the "Fetch Products" button in the button box
4. Configure fetch options in the wizard:
   - Set page size (default: 100)
   - Enable/disable fetch all pages
   - Set max pages if not fetching all
5. Click "Fetch Products" to start the import
6. View progress and results in the wizard

## Product Mapping

The module maps Stockpilot product fields to Odoo as follows:

- `title` → `name`
- `description` → `description_sale`
- `is_active` → `active`
- `brand` → (stored but not mapped)
- `category` → (stored but not mapped)
- `image_url` → (stored but not mapped)

Products are matched by name. If a product with the same name exists, it will be updated; otherwise, a new product is created.

## Dependencies

- ws_stockpilot_connector
- product

## Technical Details

- Model: `product.fetch.wizard` (TransientModel)
- Inherits: `stockpilot.configuration`
- API Endpoint: `GET https://api.stockpilot.dev/products/`
- Pagination: Supports paginated responses with `next` URL

## License

LGPL-3
