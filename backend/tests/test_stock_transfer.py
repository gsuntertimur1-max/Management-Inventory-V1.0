from backend.stock_transfer import split_transfer_qty


def test_transfer_uses_untracked_before_named_lots():
    untracked, tracked = split_transfer_qty(100, 60, 30)
    assert untracked == 30
    assert tracked == 0


def test_transfer_moves_named_lots_after_untracked_is_exhausted():
    untracked, tracked = split_transfer_qty(100, 60, 70)
    assert untracked == 40
    assert tracked == 30


def test_transfer_all_tracked_when_stack_has_full_lot_coverage():
    untracked, tracked = split_transfer_qty(100, 100, 25)
    assert untracked == 0
    assert tracked == 25
