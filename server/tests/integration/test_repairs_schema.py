from sqlalchemy import Engine, inspect


def test_migration_creates_expiring_repair_preview_boundary(
    test_database_engine: Engine,
) -> None:
    columns = {
        column["name"] for column in inspect(test_database_engine).get_columns("repair_previews")
    }

    assert columns == {
        "preview_id",
        "status",
        "original_file_id",
        "source_sha256",
        "uploaded_by",
        "factory_id",
        "line_count",
        "box_count",
        "total_quantity",
        "validation_errors",
        "validation_warnings",
        "expires_at",
        "confirmed_at",
        "confirmed_repair_id",
        "created_at",
        "updated_at",
    }


def test_migration_creates_ordered_repair_preview_line_boundary(
    test_database_engine: Engine,
) -> None:
    columns = {
        column["name"]
        for column in inspect(test_database_engine).get_columns("repair_preview_lines")
    }

    assert columns == {
        "line_id",
        "preview_id",
        "source_sheet",
        "source_row",
        "source_order",
        "box_number",
        "supplier_number",
        "factory_name",
        "source_sku_id",
        "source_product_id",
        "product_name",
        "properties_value",
        "quantity",
        "reason",
        "matched_product_id",
        "matched_variant_id",
        "validation_errors",
        "validation_warnings",
        "created_at",
    }


def test_migration_creates_independent_repair_order_boundary(
    test_database_engine: Engine,
) -> None:
    columns = {
        column["name"] for column in inspect(test_database_engine).get_columns("repair_orders")
    }

    assert columns == {
        "repair_id",
        "repair_no",
        "factory_id",
        "status",
        "warehouse_return_quantity",
        "repaired_quantity",
        "scrapped_quantity",
        "returned_quantity",
        "return_date",
        "original_file_id",
        "source_sha256",
        "created_by",
        "archived_by",
        "archived_at",
        "created_at",
        "updated_at",
    }


def test_migration_creates_immutable_repair_inspection_line_boundary(
    test_database_engine: Engine,
) -> None:
    columns = {
        column["name"]
        for column in inspect(test_database_engine).get_columns("repair_inspection_lines")
    }

    assert columns == {
        "inspection_line_id",
        "repair_id",
        "source_sheet",
        "source_row",
        "source_order",
        "box_number",
        "product_id",
        "variant_id",
        "source_sku_id",
        "source_product_id",
        "product_name",
        "properties_value",
        "warehouse_return_quantity",
        "reason",
        "created_at",
    }


def test_migration_creates_repair_number_counter_boundary(
    test_database_engine: Engine,
) -> None:
    columns = {
        column["name"]
        for column in inspect(test_database_engine).get_columns("repair_number_counters")
    }

    assert columns == {"business_date", "next_sequence", "updated_at"}
