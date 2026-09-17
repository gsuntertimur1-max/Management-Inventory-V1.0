from backend.loading_plan import build_loading_plan, loading_route_label


def test_loading_plan_groups_by_unit_and_preserves_stack_document_product():
    items = [
        {"name": "Beras A", "documentNo": "SO/001", "stackCode": "18/A01", "qty": 10},
        {"name": "Beras B", "documentNo": "SO/002", "stackCode": "18/B02", "qty": 20},
        {"name": "Minyak", "documentNo": "SO/003", "stackCode": "19/A01", "qty": 30},
    ]
    plan = build_loading_plan(items)
    assert [row["unit"] for row in plan] == ["18", "19"]
    assert plan[0]["stacks"] == ["18/A01", "18/B02"]
    assert plan[0]["documents"] == ["SO/001", "SO/002"]
    assert plan[0]["products"] == ["Beras A", "Beras B"]
    assert plan[0]["qty"] == 30
    assert plan[1]["stacks"] == ["19/A01"]
    assert loading_route_label(items) == "Unit 18 (18/A01, 18/B02) -> Unit 19 (19/A01)"


def test_loading_plan_supports_mp1():
    items = [{"name": "Beras", "documentNo": "SO/100", "stackCode": "MP1/A01", "qty": 5}]
    plan = build_loading_plan(items)
    assert plan[0]["unit"] == "MP1"
    assert loading_route_label(items) == "MP1 (MP1/A01)"
