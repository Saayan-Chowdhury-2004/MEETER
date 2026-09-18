from app.perception.state_tracker import StateTracker


def test_url_dedup():
    st = StateTracker()
    assert st.is_new_url("https://github.com/a/b")
    st.remember_url("https://github.com/a/b")
    assert not st.is_new_url("https://github.com/a/b")


def test_message_dedup():
    st = StateTracker()
    st.remember_message("hello world")
    assert not st.is_new_message("hello world")
    assert st.is_new_message("different")


def test_bounded_set_eviction():
    from app.perception.state_tracker import BoundedSeenSet

    bs = BoundedSeenSet(max_entries=3)
    for i in range(5):
        bs.mark(f"item-{i}")
    assert not bs.seen("item-0")  # evicted
    assert bs.seen("item-4")
